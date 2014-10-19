''' A collection of tools necessary for the creation and processing of time-card web forms

        Note: data coming from the web app will be a dictionary of POST data like this:
        {'end_time_03': u'', 'end_time_02': u'', 'end_time_01': u'17:23', 
        'taskduration_01': u'0', 'shot_02': u'fs303_123_999', 'shot_01': u'fs303_123_456', 
        'artistname': u'Bob', 'start_time_03': u'', 'start_time_02': u'', 'recorddate': 
        u'2013-04-17', 'start_time_01': u'13:54', 'task_01': u'Roto', 'task_02': u'Roto'}

'''
__author__ = 'tom stratton t.stratton at tomstratton dot net'

import datetime
import os
import traceback
import ConfigParser # the secret keys to log into shotgun are stored in a config file
from shotgun_api3 import Shotgun
try: # for early versions of python json is not supported...
    import json
except ImportError:
    import simplejson as json

try: # for early versions of python namedtuple is not supported so  create one
    from collections import namedtuple
except ImportError:
    # implementation of namedtuple from Python Cookbook 2nd edition (slight modifications)
    from operator import itemgetter
    def namedtuple(typename, attribute_names):
        " create and return a subclass of `tuple', with named attributes "
        # make the subclass with appropriate __new__ and __repr__ specials
        nargs = len(attribute_names)
        class supertup(tuple):
            __slots__ = () # save memory, we don't need per-instance dict
            def __new__(cls, *args):
                if len(args) != nargs:
                         raise TypeError, '%s takes exactly %d arguments (%d given)' % (
                                typename, nargs, len(args))
                return tuple.__new__(cls, args)
            def __repr__(self):
                return '%s(%s)' % (typename, ', '.join(map(repr, self)))
        for index, attr_name in enumerate(attribute_names):
            setattr(supertup, attr_name, property(itemgetter(index)))
        supertup.__name__ = typename
        return supertup


TimeCardEntry = namedtuple('TimeCardEntry',['start','end','duration'])
TaskTrackerEntry = namedtuple('TaskTrackerEntry', ['shot_list', 'task_list', 'duration'])
CONFIG_FILE = '/path/to/config/file/on/server/sgkeys.cfg' 
THIS_SCRIPT_CONFIG = 'time_card_tools'  # the config file section used by this script 

# In order to avoid hard coding these values in various places (including the html
#   templates!) they are entered here. They should be moved to the config file!
DEFAULT_SHOT_CHOICE = 'Select a Shot'
DEFAULT_USER_CHOICE = 'Who are you?'
OVERHEAD_TASK_NAME = 'Admin'
NON_LISTED_SHOT_NAME = 'Other'
# these are the shot/sequence status codes that indicate a shot should be listed in the UI
STATUS_INIDCATING_OK_TO_LIST = ['ip', 'kbk', 'wtg'] 
# project to assign tasks to if there is no valid project found by parsing the data
ERROR_PROJECT = {'id': 66, 'type': 'Project'}
TASK_LIST = ['2D Paint',
            '3D Track',
            'Character Animation',
            'Character Matchmove',
            'Cloth Simulation',
            'Color and Lighting',
            'Composite',
            'FX Animation',
            'Matte Paint',
            'Roto/Wire Removal',
            'Character Animation TD',
            'Technical Direction (TD)',
            OVERHEAD_TASK_NAME,
            ]

class ConfigError(Exception):
    def __init__(self, value):
        self.message = value
    def __str__(self):
        return repr(self.message)

###################### START ROUTINES FOR THE TIME-CARD DATA ENTRY PAGES ###################

def pack_globals(dict):
    '''
    A procedure which modifies the dict passed in by adding script globals to the dict
    it is used in order to maintain consistency between the html template constants and 
    the constants in this script
    '''
    dict['default_shot_choice'] = DEFAULT_SHOT_CHOICE
    dict['default_user_choice'] = DEFAULT_USER_CHOICE
    dict['overhead_task_name'] = OVERHEAD_TASK_NAME
    dict['non_listed_shot_name'] = NON_LISTED_SHOT_NAME


def get_users( post_dict):
    '''create a shotgun instance then return a list of users(as strings) that are then 
    displayed on the time-card
          these are the active users at any given time who are required to fill in time 
          cards (flag in SG)
    '''

    if post_dict['permanent_userlist']:
        # user data already tracked -  check for a non-default selection
        result = json.loads(post_dict['permanent_userlist'])
        current_artist = post_dict['artistname']
        if current_artist != DEFAULT_USER_CHOICE:
            result = [current_artist] # set the list to ONLY the selected user so we can't mess up the shot list
        return result

    else:
        # get the users from Shotgun
        sg = get_shotgun_instance()
        filters = [ ['sg_status_list', 'is', 'act' ],]
        fields = ['name', 'login']
        users = sg.find('HumanUser', filters, fields)
        user_list = [ user['name'] for user in users if user['name'] not in ( 'Template User', 'Shotgun Support') ]
        user_list.sort()
        user_list.insert(0,DEFAULT_USER_CHOICE)

    return user_list


def get_date(post_dict=None):
    '''returns the current date in the format required for the web-form to use correctly
        eg: "2013-04-17" unless the post dict alreay has a date, then it returns that date.

        If no post_dict is given, return the current date
    '''
    # todo add logic to prevent future dates!
    if post_dict:
        if post_dict['recorddate']:
            return post_dict['recorddate']
    web_date_format_string = '%Y-%m-%d' # "2013-04-17"
    return datetime.date.today().strftime(web_date_format_string)


def get_dates(post_dict=None):
    '''returns the current date in the format required for the web-form to use correctly
       eg: "2013-04-17" unless the post dict alreay has a date, then it returns that date.
         it also returns correctly formatted version to today and 7 days ago to use as
         max and min values in the HTML input form
       If no post_dict is given, return the current date instead of the user selected date

        returns ( user selected date, today's date, date of 7 days ago)
    '''
    web_date_format_string = '%Y-%m-%d' # "2013-04-17"
    today_date =  datetime.date.today().strftime(web_date_format_string)
    last_week = ( datetime.date.today()
                    - datetime.timedelta(7)).strftime(web_date_format_string)
    user_date = today_date
    if post_dict and post_dict['recorddate']:
        user_date = post_dict['recorddate']
    return user_date, today_date, last_week


def get_time_card_entries(post_dict):
    '''given the data dictionary from the POST request, parse it for time card entries. 
        Return a list of namedtuples (TimeCardEntry) For each "line" of data that is not 
        empty. It is the responsibility of the calling function to append a blank line to 
        the actual web form and to make sure 2 lines are displayed to the user. Partially 
        filled in info is returned correctly and 0 is returned for undetermined durations.

        timecardentry formats: times are either 'hh:mm' in 24 hour time format OR None
                               durations are decimal hours to two decimal places
    '''
    result = []
    start_key = 'start_time_%02d'
    end_key = 'end_time_%02d'
    seconds_per_hour = 60 *60 + 1.0e-50 # make this a float 
    i=1
    duration = 0 # used outside of the loop to see if we need to add a line to the form
    while start_key % (i) in post_dict:
        start_string = post_dict[start_key % (i)] # u'hh:mm' in 24 hour time format 
        end_string = post_dict[end_key % (i)]
        today = datetime.date.today()
        if start_string and end_string:
            # there is a value in both of the two time fields so we convert 
            # convert the time as string to a time object by splitting on ':'--> integers
            start_time = datetime.time(*[int(u) for u in start_string.split(':')])
            end_time = datetime.time(*[int(u) for u in end_string.split(':')])
            start_time = datetime.datetime.combine(today,start_time) #datetime object
            end_time = datetime.datetime.combine(today,end_time)
            duration = end_time - start_time # timedelta object
            # convert to hours - assuming we are in the same day
            duration = duration.seconds / seconds_per_hour 
            # convert to string with reasonable rounding to 2 decimal places
            duration_string = '%.2f' % (duration + .0001) 
            result.append(TimeCardEntry(start_string, end_string, duration_string) )

        elif start_string:
            result.append(TimeCardEntry(start_string,None,'0.00'))
            duration = 0 # suppress new line in form
        elif end_string:
            result.append(TimeCardEntry(None, end_string, '0.00'))
            duration = 0 # suppress new line in form
        i += 1
        
    if duration and duration > 0.01:
        result.append(TimeCardEntry(None,None,'0.00'))

    return result


def get_tasks():
    '''returns the list of tasks that we want to track - as provided by management'''
    return TASK_LIST


def update_shotlist(post_dict, form_data_dict):
    '''
    This is a procedure call - not a function!
    Updates the form_data_dict IN PLACE with appropriate PERMANENT shot list based on
    1 - IF the user has been selected
    2 - if the data has already been generated

    This is intended to ensure that the call to the sg database only happens once for each
    session and the json-ified data is stored (and then passed around).
    '''
    artist_name = post_dict['artistname'] #currently selected artist NAME
    if artist_name == DEFAULT_USER_CHOICE:
        # We haven't got a user yet - keep an empty list
        form_data_dict['permanent_shotlist'] = ''
        return
    if post_dict['permanent_shotlist']: # it has been set before...
        # the data has already been json-ified so send it back
        form_data_dict['permanent_shotlist'] = post_dict['permanent_shotlist']
        return
    else: # not yet set so create it from the artist name and a database lookup
        sg = get_shotgun_instance()
        active_projects = sg.find('Project', [['sg_status', 'is', 'Active'],] )
        filters = [['sg_assigned_to', 'name_contains', artist_name],
                   ['project', 'in', active_projects],
                   ['sg_status_list', 'in', STATUS_INIDCATING_OK_TO_LIST ],
                   ]
        fields = ['code', 'sg_assigned_to', 'project']
        shots = sg.find('Shot', filters, fields)
        sequences = sg.find('Sequence', filters, fields)
        shots = [ x['code'] for x in shots]
        sequences = [ x['code'] for x in sequences]
        shots.extend(sequences)
        shots.sort()
        shots.insert(0,DEFAULT_SHOT_CHOICE)
        form_data_dict['permanent_shotlist'] = json.dumps(shots)
        # having created a shotlist the user should not be changed or shots won't be right
        post_dict['permanent_userlist'] = json.dumps([post_dict['artistname'],])
        return

def get_shot_list(artist_name, form_data_dict):
    '''returns a list of shot names (strings) that are most likely to have been worked on 
    by the artist the first item in the list should always be "Select Shot" and the last 
    item should always be "Other"

    This list is used to generate the drop-down options for each line in the task tracking 
    section of the form
    '''
    if artist_name == DEFAULT_USER_CHOICE:
        # we can't to pick shots until after a user has been selected
        return [DEFAULT_SHOT_CHOICE]

    result = json.loads(form_data_dict['permanent_shotlist'])
    result.append(NON_LISTED_SHOT_NAME)
    result.append(OVERHEAD_TASK_NAME)
    return result

def calculate_time_total(record_list):
    '''given the user data find the total sum of task or work time logged'''
    total_time = 0
    for record in record_list:
        total_time += float(record.duration)
    return '%.2f' % (total_time)

def get_shotgun_instance():
    '''return a shotgun instance for use by these scripts'''
    try:
        # Load Config Data for shogun access
        if os.path.isfile(CONFIG_FILE):  # test for existence of config file
            config = ConfigParser.RawConfigParser()
            config.read(CONFIG_FILE)
            SERVER_PATH = config.get(THIS_SCRIPT_CONFIG, 'SERVER_PATH')
            SCRIPT_USER = config.get(THIS_SCRIPT_CONFIG, 'SCRIPT_USER')
            SCRIPT_KEY = config.get(THIS_SCRIPT_CONFIG, 'SCRIPT_KEY')
        else:
            raise ConfigError('Your server side configuration file is missing!')

        # initiate a shotgun API instance
        sg = Shotgun(SERVER_PATH, SCRIPT_USER, SCRIPT_KEY)

    except ConfigError:
        print 'there was an error parsing the script configuration file'
        traceback.print_exc()
        raise
    return sg

def get_task_tracker_entries(post_dict, form_data_dict=None):
    '''given the data dictionary from the POST request, parse it for task time entries. 
        Return a list of namedtuples (TaskTrackerEntry) For each "line" of data that is 
        not empty.

        The returned list should have the complete information necessary to generate the 
        form selects for task tracking with the default values changed so that user 
        supplied values are a the beginning of each list of options.

        This routine will return all the necessary info - including the addition of the 
        "next" line if all values are filled in in the (current) final line

        tasktrackerentry formats: 
            shot_list is a list of shot names in order of appearance in a select list
                (the first value is the currently selected value)
            task_list is a list of tasks which is modified to show the user selected value
                in the first postion
            duration is the user entered duration (time spent) on that task, or 0
    '''
    result = []
    shot_key = 'shot_%02d'
    task_key = 'task_%02d'
    duration_key = 'taskduration_%02d'
    artist_name = post_dict['artistname']
    default_shot_list = get_shot_list( artist_name, form_data_dict)
    default_task_list = get_tasks()
    i=1
    selected_shot_string = DEFAULT_SHOT_CHOICE
    users_duration_string = '0.00'

    while shot_key % (i) in post_dict:
        selected_shot_string = post_dict[shot_key % (i)]
        selected_task_string = post_dict[task_key % (i)]
        users_duration_string =  post_dict[duration_key % (i)]
        shots_to_report = list(default_shot_list)
        tasks_to_report = list(default_task_list)

        if selected_shot_string != shots_to_report[0]:
            try:
                shots_to_report.remove(selected_shot_string)
            except ValueError:
                #this means that the item was not in the list - OK to ignore
                pass
            del shots_to_report[0]
            shots_to_report.insert(0,selected_shot_string)
        if selected_task_string != tasks_to_report[0]:
            tasks_to_report.remove(selected_task_string)
            tasks_to_report.insert(0,selected_task_string)

        if selected_shot_string == OVERHEAD_TASK_NAME:
            tasks_to_report = [OVERHEAD_TASK_NAME]

        result.append(TaskTrackerEntry(shots_to_report, tasks_to_report,users_duration_string))
        i += 1
        
    while len(result) < 2:
        result.append(TaskTrackerEntry(default_shot_list, default_task_list, '0.00'))
    if selected_shot_string != DEFAULT_SHOT_CHOICE or users_duration_string != '0.00':
        result.append(TaskTrackerEntry(default_shot_list, default_task_list, '0.00'))
        
    return result


def make_empty_form_data():
    '''
    This is called with no options and returns the time card form data necessary to initialize the form
    before any user data has been collected
    '''
    shotgun_instance = get_shotgun_instance()
    dummy_post_dict = {
        'artistname': DEFAULT_USER_CHOICE,
        'permanent_userlist': None,
                }

    empty_form_data = {}
    empty_form_data['artists'] = get_users( dummy_post_dict)
    empty_form_data['permanent_userlist'] = json.dumps(empty_form_data['artists'])

    empty_form_data['totaltime'] = '0.00'
    empty_form_data.update(dict(zip(['recorddate', 'maxdate', 'mindate'],get_dates())))
    empty_form_data['timecards'] = [TimeCardEntry(None,None,'0.00'),
                                    TimeCardEntry(None,None,'0.00')]
    empty_form_data['taskrecords'] = get_task_tracker_entries(dummy_post_dict)
    empty_form_data['totaltasktime'] = '0.00'
    empty_form_data['oksubmit'] = False
    empty_form_data['remainingtime'] = None
    empty_form_data['permanent_shotlist'] = ''
    pack_globals(empty_form_data)
    return empty_form_data

def get_form_data(post_dict):
    '''
    This is called as part of the ajax cycle - the incoming data is the current user input

    New lines in the form can be created based on the existing data and calculations can 
    be done here to ensure that we are getting the UI response that we desire
    '''

    form_data_dict = {}
    form_data_dict['oksubmit'] = False #assume NOT ok to submit until tested
    form_data_dict['artists'] = get_users( post_dict)
    form_data_dict.update(dict(zip(['recorddate', 
                                    'maxdate', 'mindate'],get_dates(post_dict))))

    update_shotlist(post_dict, form_data_dict)

    form_data_dict['taskrecords'] = get_task_tracker_entries(post_dict, form_data_dict)
    form_data_dict['timecards'] = get_time_card_entries(post_dict)
    if len(form_data_dict['timecards']) < 1:
        form_data_dict['timecards'] = [TimeCardEntry(None,None,'0.00'),
                                        TimeCardEntry(None,None,'0.00'),]
    if len(form_data_dict['timecards']) < 2:
        form_data_dict['timecards'].append(TimeCardEntry(None,None,'0.00'))

    form_data_dict['totaltime'] = calculate_time_total(form_data_dict['timecards'])
    form_data_dict['totaltasktime'] = calculate_time_total(form_data_dict['taskrecords'])
    if ( float(form_data_dict['totaltime']) > 0.01
         and
        (float(form_data_dict['totaltime']) - float(form_data_dict['totaltasktime']))**2 < 0.001):
        form_data_dict['oksubmit'] = True
    form_data_dict['remainingtime'] = float(form_data_dict['totaltime']) - 
                                            float(form_data_dict['totaltasktime'])
    if -0.01 < form_data_dict['remainingtime'] < 0.01:
        form_data_dict['remainingtime'] = None
    for record in form_data_dict['taskrecords']:
        if float(record.duration) > 0.01 and record.shot_list[0] == DEFAULT_SHOT_CHOICE:
            # there is a default shot associated with a non-zero entry. FAIL!
            form_data_dict['oksubmit'] = False
    form_data_dict['permanent_userlist'] = post_dict['permanent_userlist']
    pack_globals(form_data_dict)
    return form_data_dict

def next_element( last_element):
    '''
    given the name of the element on the page that was changed return the element ID that 
    should receive focus
    '''
    mapper = {
            'recor': 'start_time_01',
            'artis': 'recorddate',
            'task_': 'taskduration_',
            'shot_': 'task_',
            'taskd': 'shot_',
            'start': 'end_time_',
            'end_t': 'start_time_'
        }
    result = mapper[last_element[:5]]
    if result.endswith('_') and (last_element.startswith('end') or last_element.startswith('taskd')):
        i = int(last_element[-2:]) + 1
        result += '%02d' % (i)
    elif result.endswith('_'):
        i = int(last_element[-2:])
        result += '%02d' % (i)

    return result


###################### END ROUTINES FOR THE TIME-CARD DATA ENTRY PAGES ###################
###################### START ROUTINES FOR PARSING DATA INTO SHOTGUN DATABASE ###################

def create_sg_time_card(sg, sg_user, start_time, end_time, duration):
    '''
    Given a shotgun instance, artist, start, end and duration: update shotgun by
      creating the time card. In case of error - report the error and log appropriately.

      Note: that a "time card" is a custom entity created by MastersFX and is not part of 
        the default entity group

    Expected errors - shotgun not available(?)
        nothing else should fail - the user and other info is well scrubbed and validated

    sg : a shotgun instance
    sg_user : a shotgun user dict with at least {'id': 40,  'type': 'HumanUser'}
    start_time: datetime.datetime object representing the start time in local timezone
    end_time: see start_time - the end time of the record
    duration: the duration in integer minutes of the time-card
    '''
    data = {
        'sg_worker': [sg_user],
        'sg_end_time' : end_time,
        'sg_start_time' : start_time,
        'sg_duration' : duration
        }
    try:
        card = sg.create('CustomNonProjectEntity01',data,return_fields=['code'])
        if not card:
            print 'a time card was not created'
            # todo add a custom error and raise it here
    except:
        print 'there was an error creating a time card!'
        raise

def create_sg_task_log (sg, sg_user, shot_or_sequence_name, task_name,
                        duration, datestring, status='rev',description=''):
    '''
    Create a shotgun 'time log' entity for tracking task times. This will add non-default
     information to SG in the form of a special task field ('sg_dmfx_global_tasks') that
     is used to track budgeting by MastersFX

     sg : a shotgun instance
     sg_user : a shotgun user dict with at least {'id': 40,  'type': 'HumanUser'}
     shot_or_sequence_name: the name of a shot or sequence that is expected to be in SG
        note - this field may contain hand typed info and may not represent an actual shot
     task_name: the custom MastersFX tasks that are being tracked for budgeting - list exists in this code
     duration: integer representing the number of minutes to use as the task duration
     status: the status to set the shotgun time log to - this must be one of the valid sg status strings
        (may have been set to almost any value in the SG ui)
     description: if passed, this string will be used as the description of the time log entry.
        currently being used to indicate errors with the data coming in from the user. This will be set
        to the user entered shot name if there is no matching shot/sequence in the sg database.

    '''
    try:
        #find the shot or sequence
        sg_filters = [ ['code', 'is', shot_or_sequence_name ], ]
        sg_fields = ['project', ]
        entity = sg.find_one('Shot', sg_filters, sg_fields)
        if not entity: # not shot, try a sequence
            entity = sg.find_one('Sequence', sg_filters, sg_fields)
        if not entity: # if entity is still None then the user made a data entry error
            # try to get the project from the first field of the data
            proj_filters = [ ['name', 'is', shot_or_sequence_name.split('_')[0] ], ]
            project = sg.find_one('Project', proj_filters)
            if not project: # assign record to the "internal" project - clean-up manually
                project = ERROR_PROJECT
            # assign the user-supplied shot name to the description for manual cleaned up
            error_message = 'Attention: user supplied shot/sequence not found: %s'
            description = error_message % (shot_or_sequence_name)
            entity = None
        else:
            # get and remove the project from the shot/seq or shotgun will barf @ create
            project = entity.pop('project',ERROR_PROJECT)
        #duration in minutes, description blank or will be filled in with "New Time Log" 
        #   date-yyyy-mm-dd, status is pending review so that we can do reporting
        data = {
                'user':sg_user,
                'entity': entity,
                'sg_dmfx_global_tasks': task_name,
                'project': project,
                'sg_status': status,
                'duration' : int(duration),
                'date' : datestring,
                'description' : description,
                } 
        log = sg.create('TimeLog', data, return_fields=['code'])
    except:
        print 'there was an error creating a time log (task entry)!'
        raise


def add_timedata_to_shotgun(time_card_dict):
    '''
    This is a PROCEDURE that takes user data that has been passed through a web
      form via json and updates shotgun appropriately. While this is running the
      user is presented with a "please wait" message on the web page

      That message is replaced with the return value of this PROCEDURE - it can NOT
        fail - it has to succeede, even if it does not manage to get all the data into SG

    Example input data:
        {u'artistname': u'Jason Jue',
         u'end_time_01': u'10:30',
         u'end_time_02': u'',
         u'recorddate': u'2013-09-09',
         u'shot_01': u'',
         u'shot_02': u'Select a Shot',
         u'start_time_01': u'10:00',
         u'start_time_02': u'',
         u'task_01': u'2D Paint',
         u'task_02': u'2D Paint',
         u'taskduration_01': u'.5',
         u'taskduration_02': u'0.00'}
    '''
    try:
        sg=get_shotgun_instance()
        timecard = 'CustomNonProjectEntity01'
        timelog = 'TimeLog'
        user_filters = [['name', 'is', time_card_dict['artistname']],]
        user_fields = []
        sg_user = sg.find_one('HumanUser', user_filters, user_fields)
        yyyy,mm,dd = [int(x) for x in time_card_dict['recorddate'].split('-')]

        # parse the time card entries
        for i in range(1,100):
            start_key = 'start_time_%02d' % (i)
            if start_key in time_card_dict:
                if time_card_dict[start_key]:
                    start_hh,start_mm = [int(x) for x in 
                                      time_card_dict['start_time_%02d' % (i)].split(':')]
                    end_hh,end_mm = [ int(x) for x in 
                                       time_card_dict['end_time_%02d' % (i)].split(':') ]
                    start_time = datetime.datetime(yyyy,mm,dd,start_hh,start_mm)
                    end_time = datetime.datetime(yyyy,mm,dd,end_hh,end_mm)
                    duration_obj = end_time - start_time
                    duration = duration_obj.seconds/60
                    create_sg_time_card(sg, sg_user, start_time,end_time,duration)
            else: # no more user data to parse
                break

        # parse  the task entries
        for i in range(1,100):
            duration_key = 'taskduration_%02d' % (i)
            if duration_key in time_card_dict:
                if float(time_card_dict[duration_key]) > 0.005:
                    shot_or_sequence_name = time_card_dict['shot_%02d' % (i)]
                    task_name = time_card_dict['task_%02d' % (i)]
                    duration = float(time_card_dict[duration_key]) # in decimal hours
                    duration = int(0.499 + duration * 60) # in integer minutes
                    datestring = '%d-%02d-%02d' % (yyyy,mm,dd)
                    create_sg_task_log (sg, sg_user, shot_or_sequence_name, task_name, duration, datestring)
            else: # no more user data to parse
                break
        return "Timecard data successfully entered into shotgun"

    except:
        return traceback.format_exc()
