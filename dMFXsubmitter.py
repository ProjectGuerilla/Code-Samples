'''
GUI based application to submit versions of Shots, Assets and Elements to Shotgun
 and to provide screener movie files as well (as an option)
'''
__author__ = 'tom stratton tom@tomstratton dot net'
__version__ = '0.9.5 March 20 2013'

from submitter_UI import Ui_dMFXsubmitter
from submitter_dialog import Ui_Dialog
from PyQt4.QtCore import *
from PyQt4.QtGui import *
from shotgun_api3 import Shotgun
from pprint import pformat, pprint
from dmfx_tools.file_tools import symlinker, REVIEW_FOLDER_GLOB
from dmfx_tools.name_tools import version_number_from_string, show_name_from_string, shot_name_from_string
import os
import traceback
import glob
import datetime
from formic import formic
import types

SERVER_PATH = 'https://YOURURL.shotgunstudio.com'  # your server path here
SCRIPT_USER = 'test_script'  # your script name in the shotgun scripts page
SCRIPT_KEY = '756b5611332e973a5b1a1927eb3513c2b5d4cc2f'  # your key here - from the SG scripts page
INITIALS_LIST = ['Vancouver Artists', ]
STARTING_USER_LIST_TEXT = 'Please Select...'
MOVIE_FILE_EXTENSION_LIST = ('.mp4', '.mov')

class ShotgunError(Exception):
    pass

# Monkey Patches to be applied to lineEdits to allow files to be dragged onto them
mimeData = QMimeData()
def dragEnterEvent(self, e):
    e.accept()
    if e.mimeData().hasUrls():
        e.accept()
    else:
        e.ignore()

def dropEvent(self, e):
    file_paths = e.mimeData().urls()
    self.setText(str(file_paths[0].toLocalFile()))

# routine to actually update shotgun using user supplied version info
def update_shotgun(sg, version_file_path, description, user_id, version_type, user_initial=None, calling_window=None ):
    version_file_path = str(version_file_path)
    description = str(description)
    version_file_name = os.path.split(str(version_file_path))[-1]
    version_name = os.path.splitext(str(version_file_name))[0]
    name_fields = version_name.split('_')
    look_for = '_'.join(name_fields[0:2])
    filters = [ ['code' , 'starts_with' , look_for ],]
    fields = ['code', 'project']
    found_items = sg.find( version_type, filters, fields)
    if not found_items:
        return None
    rangeend = len(name_fields)
    best_length = 0
    best_match = None

    for an_item in found_items:
        item_name = an_item['code']
        for i in range(2,rangeend):
            match_this = '_'.join(name_fields[0:i])
            if item_name.startswith(match_this) and i > best_length:
                best_length = i
                best_match = an_item

    # Display found item to user and get confirmation or allow them to pick another...
    user_report_text = 'Found a(n) {0}:\n    {1}'.format(best_match['type'],best_match['code'])
    user_report_text += '\n\nPress OK to accept this link'
    if len(found_items) >1:
        user_report_text += '\nor select a different match'
    user_report_list = [best_match['code'], ] + [ i['code'] for i in found_items if i['code'] != best_match['code'] ]
    sub_dialog = dMFXsubmitterSubDialog(
        "Linking To:", "OK", "QUIT!", user_report_text, boxeditable = False, listvalues= user_report_list, parent=calling_window )
    if sub_dialog.exec_():
        sub_dialog.close()
        button, text, pick = sub_dialog.getValues()
        if button == 'No' :
            QApplication.quit()
        if pick != best_match['code']:
            # need to give the routine the user selected thing...
            for an_item in found_items:
                if pick == an_item['code']:
                    best_match = an_item
                    break
    project_data = best_match['project']
    del best_match['project']
    data = {
        'project' : project_data,
        'code': version_name,
        'description': description,
        'entity': best_match,
        'user': {'type':'HumanUser','id': user_id},
        'sg_script_submitter_1' : {'type':'HumanUser','id': user_id},
        'sg_path_to_movie': version_file_path,
        }
    # for Vancouver Artists (eg:) add the initials so we know who is submitting
    if user_initial:
        data['tag_list'] = [user_initial,]
    # already exists?
    filters = [['code', 'is', version_name],]
    fields = ['id']
    existing_version = sg.find_one('Version', filters, fields)
    if existing_version:
        if not description:
            # remove an empty description so I don't overwrite one that already exists with a blank!
            del data['description']
        updated_version_dict = sg.update('Version', existing_version['id'], data)
        return updated_version_dict['id']
    else:
        data['created_by'] = {'type':'HumanUser','id': user_id}
        new_version_dict = sg.create( 'Version', data)
        return new_version_dict['id'] # the id of the newly created version - for use with submissions...

########################################################################################################################

def do_submit_for_review(sg, movie_file_path, version_id ):
    '''
    Takes the data provided by the user and creates symbolic links of screeners in the filesystem
    @ movie_file_path: full path to the version file
    '''
    movie_file_path = str(movie_file_path)
    #if mp4, upload and/or link movie file into shotgun
    movie_name = os.path.split(movie_file_path)[-1]
    movie_name, file_extension = os.path.splitext(movie_name)
    if file_extension.lower() == ".mp4": #upload it
        sg.upload('Version', int(version_id), movie_file_path,'sg_uploaded_movie')
    data = {
        'sg_zz_path_test' : {'link_type': 'local', 'local_path': movie_file_path},
        'sg_path_to_movie': movie_file_path
            }
    updated_version = sg.update('Version', int(version_id), data )

    # create symlink in daily review folder
    todays_review_folder = None
    show_name = show_name_from_string(os.path.split(movie_file_path)[-1])
    dirIwant = ( adir for adir in glob.glob(REVIEW_FOLDER_GLOB)
                 if show_name.lower() in adir.lower()).next()
    os.chdir(dirIwant)
    date_string = datetime.date.today().strftime('%m%d%y')
    todays_review_folder = [adir for adir in glob.glob('*') if
                            date_string.lower() in adir.lower()]
    if todays_review_folder:
        todays_review_folder = todays_review_folder[0]
    else:
        todays_review_folder = '{0}_{1}_review'.format(show_name,date_string)
        os.mkdir(todays_review_folder)
    todays_review_folder = os.path.join(os.getcwd(),todays_review_folder)
    error_list = symlinker(movie_file_path,todays_review_folder)
    if error_list:
        time.sleep(1)
        file_name = os.path.basename(movie_file_path)
        if os.path.exists(os.path.join(todays_review_folder, file_name)):
            return True
        error_list = symlinker(movie_file_path,todays_review_folder)
        #raise SystemError('Could not create symbolic link in destination folder')
        if error_list:
            return False
    return True

# sub dialog box to be called by main UI dialog as needed to collect additional user input
class dMFXsubmitterSubDialog(QDialog, Ui_Dialog):
    '''
    A simple 3-button dialog box with a text box and a drop-down menu which can be customized on the fly
    The "return_value" property holds a 3-tuple (button,box text,dropdown item) unless the user clicks on the NO button
     in which case the return_value will be arbitrarily set

    yeslabel - The label for the "Yes" button - if clicked button returned is "Yes" (default button)
    nolabel  - The label for the "No" button - if clicked button returned is "No"
    boxtext - The text that is to be put into the plain-text box (generally an error message or instruction)
    boxeditable = True - If True the user can edit the text in the box and it will be returned
    otherlabel=None   - The label for the "Other" button - if clicked button returned is "Other"
                        if omitted, then the button is not visible
    listvalues=None - if omitted, the combo-box will not be visible, otherwise this is a list that contains the
                        choices for the combo-box with the default value in [0]
    '''
    def __init__(self, mainlabel, yeslabel, nolabel, boxtext, boxeditable = True, otherlabel=None, listvalues=None, parent = None):
        super(dMFXsubmitterSubDialog, self).__init__(parent)
        #QtGui.QDialog.__init__(self,parent) # from stack overflow
        self.setupUi(self) #generic call to setup the Ui provided by Qt
        self.return_value = ['OK',None,None] # button pressed, text in box, selected item from combobox
        self.connect(self,SIGNAL('accept_'),self.accept)
        self.connect(self,SIGNAL('update'),self.updateUI)
        self.text = ''
        self.pick = ''
        if listvalues:
            self.pick = listvalues[0]
        self.pushButton_yes.setText(yeslabel)
        self.pushButton_no.setText(nolabel)
        self.plainTextEdit.setPlainText(boxtext)
        self.plainTextEdit.setEnabled(True)
        self.label.setText(mainlabel)
        if not boxeditable:
            self.plainTextEdit.setEnabled(False)
        if otherlabel:
            self.pushButton_other.setText(otherlabel)
        else:
            self.pushButton_other.hide()

        if listvalues:
            for value in listvalues:
                self.comboBox.addItem(value)
        else:
            self.comboBox.hide()
        self. emit(SIGNAL('update'))

    def updateUI(self):
        self.activateWindow() # window gets keyboard focus after redraw

    # self.pushButton_yes
    @pyqtSignature("") # this will need to have an appropriate value for each window object type
    def on_pushButton_yes_clicked(self):
        self.return_value[0] = 'Yes'
        self.return_value[1] = str(self.plainTextEdit.toPlainText())
        self. emit(SIGNAL('accept_'))

    # self.pushButton_other
    @pyqtSignature("") # this will need to have an appropriate value for each window object type
    def on_pushButton_other_clicked(self):
        self.return_value[0] = 'Other'
        self.return_value[1] = str(self.plainTextEdit.toPlainText())
        self. emit(SIGNAL('accept_'))

    # self.pushButton_no
    @pyqtSignature("") # this will need to have an appropriate value for each window object type
    def on_pushButton_no_clicked(self):
        self.return_value[0] = 'No'
        self.return_value[1] = str(self.plainTextEdit.toPlainText())
        self. emit(SIGNAL('accept_'))

    # self.comboBox_artistSelect
    @pyqtSignature("QString")
    def on_comboBox_currentIndexChanged(self):
        self.return_value[2] = str(self.comboBox.currentText())
        self.emit(SIGNAL("update"))

    def getValues(self):
        self.close()
        self.hide()
        return self.return_value

# Main UI dialog window 
class dMFXsubmitterDialog(QDialog, Ui_dMFXsubmitter):

    def __init__(self, parent = None):
        # set up the UI and variable here - don't forget to call updateUI at end
        super(dMFXsubmitterDialog,self).__init__(parent)
        self.acceptDrops()
        self.setupUi(self) # generic call to setup the Ui provided by Qt
        self.password = ''
        self.version_file_path = ''
        self.user = ''
        self.user_id = ''
        self.user_name = ''
        self.user_initials = ''
        self.submit_movie = False
        self.movie_file_path = ''
        self.description = ''
        self.login_status = False
        self.allOK = True
        self.submit_call_track = True
        self.version_type = 'Shot'
        self.created_version_id = None
        self.sg = Shotgun(SERVER_PATH, SCRIPT_USER, SCRIPT_KEY)
        self.sgu = Shotgun(SERVER_PATH, SCRIPT_USER, SCRIPT_KEY)
        self.users_with_initals = INITIALS_LIST
        self.user_list = []
        self.lineEdit_versionFile.dragEnterEvent = types.MethodType(dragEnterEvent,self.lineEdit_versionFile)
        self.lineEdit_versionFile.dropEvent = types.MethodType(dropEvent,self.lineEdit_versionFile)
        self.lineEdit_versionFile.setAcceptDrops(True)
        self.lineEdit_versionFile.setDragEnabled(True)
        self.lineEdit_forReview.dragEnterEvent = types.MethodType(dragEnterEvent,self.lineEdit_forReview)
        self.lineEdit_forReview.dropEvent = types.MethodType(dropEvent,self.lineEdit_forReview)
        self.lineEdit_forReview.setAcceptDrops(True)
        self.lineEdit_forReview.setDragEnabled(True)

        # start things happening... get the users from sg and populate them into the drop-down
        self.update_user_list()
        self.connect(self,SIGNAL('update'),self.updateUI)

        self.new_value = 'this is not a new value'
        #self.emit(SIGNAL("update"))
        self.updateUI()

    def update_user_list(self):
        filters = [ ['sg_status_list', 'is', 'act' ],]
        fields = ['name', 'login']
        users = self.sg.find('HumanUser', filters, fields)
        user_list = [ (user['name'],user['login'],user['id']) for user in users if user['name'] != 'Template User']
        user_list.sort()
        self.user_list = user_list
        self.comboBox_artistSelect.addItem('Please Select...')
        self.user = 'Please Select...'
        for user in user_list:
           self.comboBox_artistSelect.addItem(user[0])
        self.updateUI()

    def reset_to_go_again(self):
        # todo set all fields to blank, not just update the values...
        self.version_file_path = ''
        self.submit_movie = False
        self.movie_file_path = ''
        self.description = ''
        self.allOK = True
        self.created_version_id = None
        self.plainTextEdit_description.setPlainText('')
        self.lineEdit_versionFile.setText('')
        self.lineEdit_forReview.setText('')
        self.updateUI()

    def updateUI(self):
        # make sure that the UI is updated to match input
        self.activateWindow() # window gets keyboard focus after redraw
        self.allOK = True
        self.description = str(self.plainTextEdit_description.toPlainText())

        # check user and if it needs initials, activate the text box
        if self.user in self.users_with_initals:
            self.lineEdit_initials.setEnabled(True)
        else:
            self.lineEdit_initials.setEnabled(False)

        # check user to see if one has been selected... set login to default if it has and there is no login set
        if self.user == STARTING_USER_LIST_TEXT:
            self.pushButton_login.setEnabled(False)
        else:
            self.pushButton_login.setEnabled(True)
            if not self.login_status:
                self.pushButton_login.setDefault(True)

        # check to see if logged in - if not, disable everything below login
        if self.login_status:
            self.label_password.setText("** Logged In **")
            self.pushButton_login.setEnabled(False)
            self.comboBox_artistSelect.setEnabled(False)
        else:
            self.label_password.setText("Shotgun Password")
            self.pushButton_login.setEnabled(True)

        # check the submit checkbox and enable fields if set
        if self.checkBox_forReview.isChecked():
            self.lineEdit_forReview.setEnabled(True)
            self.pushButton_getForReview.setEnabled(True)
            self.submit_movie=True

        # check for movie submit check-box
        if self.submit_movie:
            self.lineEdit_forReview.setEnabled(True)
            self.pushButton_getForReview.setEnabled(True)
        else:
            self.lineEdit_forReview.setEnabled(False)
            self.pushButton_getForReview.setEnabled(False)

        # check for a need for initals
        if self.user in INITIALS_LIST:
            self.label_initials.setText('Add Your Initials')
            self.lineEdit_initials.show()
        else:
            self.label_initials.setText('')
            self.lineEdit_initials.hide()
            self.user_initials = ''
            self.lineEdit_initials.setText('')

        # check to see if the version file is a movie and, if so and the movie line is empty, fill that in
        if self.version_file_path and os.path.splitext(str(self.version_file_path).lower())[1] in MOVIE_FILE_EXTENSION_LIST and not self.movie_file_path:
            self.movie_file_path = str(self.version_file_path)
            self.lineEdit_forReview.setText(self.movie_file_path)

        # check for conditions that allow an update to happen
        conditions = True # start by assuming we can go and switch if we can't
        if self.user in INITIALS_LIST and not self.user_initials:
            conditions = False
        if conditions and not self.login_status:
            conditions = False
        if conditions and self.version_file_path and not os.path.exists(self.version_file_path):
            conditions = False
        if conditions and self.submit_movie:
            if self.movie_file_path and not os.path.exists(self.movie_file_path):
                conditions = False
            if not self.movie_file_path:
                conditions = False

        #enable the submit button if appropriate
        if conditions:
            self.pushButton_submit.setEnabled(True)
            self.pushButton_submit.setDefault(True)
        else:
            self.pushButton_submit.setEnabled(False)


    # self.pushButton_login
    @pyqtSignature("") 
    def on_pushButton_login_clicked(self):
        result = self.sgu.authenticate_human_user(self.user_name, self.lineEdit_password.text())
        if result:
            self.login_status = True
        else:
            # user tried to log in and failed - let them know
            QMessageBox.about(self, "Log In Error", "Unable to login to Shotgun using your user/pass combination, please try again")
        self.updateUI()

    # self.pushButton_getVersionFile
    @pyqtSignature("")
    def on_pushButton_getVersionFile_clicked(self):
        self.version_file_path = str(QFileDialog.getOpenFileName(self, "Select the file to submit as a Version"   ))
        if self.version_file_path:
            self.lineEdit_versionFile.setText(self.version_file_path)
        self.updateUI()

    # self.pushButton_getForReview
    @pyqtSignature("") 
    def on_pushButton_getForReview_clicked(self):
        self.movie_file_path = str(QFileDialog.getOpenFileNameAndFilter(self, "Select a movie file to submit for screening",
                                   filter= "Movies ( *.mp4 *.mov)")[0]) # the getopenfile returns a tuple of length 2
        if self.movie_file_path:
            self.lineEdit_forReview.setText(self.movie_file_path)
        self.updateUI()

    # self.pushButton_quit
    @pyqtSignature("")
    def on_pushButton_quit_clicked(self):
        QApplication.quit()

    # self.checkBox_forReview
    @pyqtSignature("bool")
    def on_checkBox_forReview_clicked(self):
        #lcheckBox_forReview boolean toggle code here
        self.submit_movie = self.checkBox_forReview.isChecked()
        self.updateUI()

    # self.comboBox_artistSelect
    @pyqtSignature("QString")
    def on_comboBox_artistSelect_currentIndexChanged(self):
        if self.user:
            self.user = self.comboBox_artistSelect.currentText()
            self.user_name = [ user[1] for user in self.user_list if user[0] == self.user][0]
            self.user_id = [ user[2] for user in self.user_list if user[0] == self.user][0]
        self.updateUI()

    # self.comboBox_version_type
    @pyqtSignature("QString")
    def on_comboBox_version_type_currentIndexChanged(self):
        self.version_type = str(self.comboBox_version_type.currentText())
        self.updateUI()

    # self.lineEdit_forReview
    @pyqtSignature("QString")
    def on_lineEdit_forReview_textEdited(self):
        self.movie_file_path = str(self.lineEdit_forReview.text())
        self.emit(SIGNAL("update"))

    # self.lineEdit_initials
    @pyqtSignature("QString")
    def on_lineEdit_initials_textEdited(self):
        self.user_initials = str(self.lineEdit_initials.text())
        self.updateUI()

    # self.lineEdit_versionFile
    @pyqtSignature("QString")
    def on_lineEdit_versionFile_textEdited(self):
        self.version_file_path = str(self.lineEdit_versionFile.text())
        self.updateUI()

    # self.lineEdit_versionFile
    @pyqtSignature("QString")
    def on_lineEdit_versionFile_textChanged(self):
        self.version_file_path = str(self.lineEdit_versionFile.text())
        self.updateUI()

    # self.plainTextEdit_description
    @pyqtSignature("")
    def on_plainTextEdit_description_textEdited(self):
        self.updateUI()

    # self.pushButton_submit   
    @pyqtSignature("")
    def on_pushButton_submit_clicked(self):
        if not self.submit_call_track:
            self.submit_call_track = True
            return
        else:
            self.submit_call_track = False

        sgerrmsg = "There were no matching {0}s, make sure that you have selected the right kind of entity and try again"
        if not self.allOK:
            return
        try:
            self.created_version_id = update_shotgun(self.sg, self.version_file_path, self.description, self.user_id, self.version_type, self.user_initials, self )
            if not self.created_version_id: # sg did not find anything! Tell the user and let them try again or quit
                self.allOK = False
                sub_dialog = dMFXsubmitterSubDialog(
                    "No Matches", "Reset", "QUIT!", sgerrmsg.format(self.version_type), boxeditable = False, parent=self )
                button, text, pick = sub_dialog.getValues()
                if sub_dialog.exec_():
                    sub_dialog.close()
                    button, text, pick = sub_dialog.getValues()
                    if button == 'No' :
                        QApplication.quit()
                    else:
                        return # return if they click on Retry
                else: return # return if they close the window

            mainlabel = "Success!"
            yeslabel = 'Go Again'
            nolabel = 'QUIT!'
            boxtext =  'Your version was successfully created'

            if self.allOK and self.submit_movie:
                if not do_submit_for_review(self.sg,self.movie_file_path,self.created_version_id):
                    # the sym-link failed for some reason after 2 tries...
                    mainlabel = "Partial Success..."
                    boxtext = "Your version was created but the movie was NOT put into today's Review Folder. Please add it manually, or resubmit the Version"

        except Exception,e:
            mainlabel = "ERROR!"
            yeslabel = 'Reset'
            nolabel = 'QUIT!'
            boxtext =  'Something Went Horribly Wrong! -\nError: {0}\n{1}'.format(e,traceback.format_exc())

        #QMessageBox.about(self, "updateUI", output_string)
        sub_dialog = dMFXsubmitterSubDialog(mainlabel,yeslabel,nolabel, boxtext )
        if sub_dialog.exec_():
            sub_dialog.close()
            button, text, pick = sub_dialog.getValues()
            if button == 'No' :
                QApplication.quit()
            else:
                self.reset_to_go_again()


if __name__ == '__main__':
    import sys
    app = QApplication(sys.argv)
    form = dMFXsubmitterDialog(parent=None)
    form.show()
    form.raise_()
    app.exec_()