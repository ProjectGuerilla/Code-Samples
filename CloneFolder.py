from pprint import pprint
import distutils.dir_util
import os
import sys
from collections import defaultdict
import shutil
from folder_structure_ui import getinput

JOBID = '[proj]'
SHOTID = '[shot]'
SHOTDUPE = '@'+SHOTID
SEQID = '[seq]'
SEQDUPE = '@' + SEQID
SOURCE_FOLDER = '/foo/bar/[proj]_proj'
ALIAS_SUFFIX = '_alias' # note that we only find alias at the END of a folder name!
__author__ = 'tom stratton tom@tomstratton dot net'


def replacestring(string_to_change, what_to_replace, replace_with):
    return string.replace(string_to_change, what_to_replace, replace_with,)

def alias_replace(main_name, path_dict):
    alias_files = [ filename for filename in path_dict.keys() if filename.endswith(ALIAS_SUFFIX)]
    for file in alias_files:
        all_full_path_to_alias = path_dict[file] # a LIST!
        original_folder_name = file.replace(ALIAS_SUFFIX, '')
        print original_folder_name
        full_path_to_original_folder = path_dict[original_folder_name]
        pprint (full_path_to_original_folder)
        if len(full_path_to_original_folder) > 1:
            # there can only be ONE
            pprint (path_dict[original_folder_name])
            print '--'+original_folder_name+'--'
            print 'There was an error with alias to ' + str(original_folder_name)

        for full_alias_path in all_full_path_to_alias:
            os.rmdir(full_alias_path.replace(JOBID, main_name))
            containing_path = os.path.split(full_alias_path)[0] # just the container directory
            os.chdir(containing_path.replace(JOBID, main_name))
            try:
                os.symlink(full_path_to_original_folder[0].replace(JOBID, main_name), original_folder_name)
            except OSError: # there is alread a sym link with this name in the folder - ok to pass
                pass

def folder_populator(template_path , destination_container , main_name , update,   sub_names, sequences, replace_alias ):
    print 'inside the function'
    #set up path names, etc.
    dest_folder_name = os.path.split(template_path)[1]
    dest_folder_name = dest_folder_name.replace(JOBID,main_name)
    dest_folder_name = os.path.join(dest_folder_name,'') # need to add a trailing slash to make later steps work!
    full_destination_path = os.path.join(destination_container, dest_folder_name)

    def replace_sub_names(current_path,new_folder_name,sub_name, search_for):
        for (dirpath, dirnames, filenames) in os.walk(os.path.join(current_path,new_folder_name), topdown=False):
            os.chdir(dirpath)
            for dirname in dirnames:
                os.rename(dirname, dirname.replace(search_for,sub_name))
            os.chdir(current_path)

    if update:
        print 'inside update-1'
        if not os.path.exists(full_destination_path):
            if os.path.split(destination_container)[1] == dest_folder_name:
                # user set the path incorrectly and chose the existing project folder
                full_destination_path = destination_container
                #test for the correct folder again...
                if not os.path.exists(full_destination_path): #still not right!
                    print 'terminating - the destination does not already exist! Can not update'
                    sys.exit()

            else:
                print 'terminating - the destination does not already exist! Can not update'
                sys.exit()
        print 'inside update-2'
        new_dest_path = os.path.join(full_destination_path, 'temp')
        if not os.path.exists(new_dest_path):
            os.mkdir(new_dest_path)

        #make a complete structure inside the 'temp' folder
        folder_populator(  template_path , new_dest_path, main_name , False , sub_names, sequences, False)

        print 'inside update-3'
        # parse through the new folder and the old folder, copying stuff across where necessary...
        for (dirpath, dirnames, filenames) in os.walk(os.path.join(new_dest_path,dest_folder_name)):
            os.chdir(dirpath) # make path handling easier by working in the current directory
            dirpath_split = dirpath.split(os.path.join('temp', dest_folder_name))
            final_path = os.path.join(*dirpath_split)

            for dir in dirnames:
                # print os.path.join(final_path,dir)
                if not os.path.exists(os.path.join(final_path,dir)):
                    # copy the dir that is not in the original structure over
                    #then remove it from the list so we don't process down into it
                    shutil.copytree(dir, os.path.join(final_path, dir))
                    dirnames.remove(dir)
        print 'inside update-4'
        # clean up the temporary project folder when done...
        _= distutils.dir_util.remove_tree(os.path.join(new_dest_path,dest_folder_name))
        print 'inside update-5'
        # now build paths for alias replace
        path_dict = defaultdict(list)
        for (dirpath, dirnames, filenames) in os.walk(full_destination_path, topdown=False):
            # os.chdir(dirpath)
            for dirname in dirnames:
                final_name = dirname.replace(JOBID, main_name)
                path_dict[final_name].append(os.path.join(dirpath,final_name))
                # do the alias replace
        print 'ending update section of if'

    else: # create a new job
        print 'in else section - no update!'
        if os.path.exists(full_destination_path):
            print 'terminating - the destination already exists'
            sys.exit()

        _ = distutils.dir_util.copy_tree(template_path,full_destination_path)

        # first pass - make duplicates of all the shot folders
        for (dirpath, dirnames, filenames) in os.walk(full_destination_path):
            os.chdir(dirpath)
            for dirname in dirnames:
                if dirname.find(SHOTDUPE) >= 0:
                    #make multiple copies of shot template directories
                    for sub_name in sub_names:
                        new_folder_name = dirname.replace(SHOTDUPE, sub_name)
                        _ = distutils.dir_util.copy_tree(dirname,new_folder_name)
                        replace_sub_names(dirpath,new_folder_name,sub_name, SHOTID)
                    # now, remove the template directory
                    _= distutils.dir_util.remove_tree(os.path.join(dirpath,dirname))

        # second pass - make duplicates of all the sequence folders
        for (dirpath, dirnames, filenames) in os.walk(full_destination_path):
            os.chdir(dirpath)
            for dirname in dirnames:
                if dirname.find(SEQDUPE) >= 0:
                    #make multiple copies of shot template directories
                    for sub_sequence in sequences:
                        new_folder_name = dirname.replace(SEQDUPE, sub_sequence)
                        _ = distutils.dir_util.copy_tree(dirname,new_folder_name)
                        replace_sub_names(dirpath,new_folder_name,sub_sequence, SEQID)
                        # now, remove the template directory
                    _= distutils.dir_util.remove_tree(os.path.join(dirpath,dirname))

        # now change all occurrences of the JOBID tag and create a dict of file paths for alias replacement
        path_dict = defaultdict(list)
        for (dirpath, dirnames, filenames) in os.walk(full_destination_path, topdown=False):
            os.chdir(dirpath)
            for dirname in dirnames:

                final_name = dirname.replace(JOBID, main_name)
                os.rename(dirname, final_name)
                path_dict[final_name].append(os.path.join(dirpath,final_name))

        print 'ending else section'

    # do the alias replace
    print 'about to alias'
    if replace_alias:
        alias_replace(main_name, path_dict)
    return None

if __name__ == '__main__':
    user_input = getinput()

    if user_input['cancel'] == '0':
        gui_separator = '[return]'
        source_folder = user_input['template_folder']
        destination_folder = user_input['destination_container']
        main_name = user_input['main_name']
        update = True if int(user_input['update']) == 1 else False
        shot_list = [item.strip() for item in user_input['shotlist'].replace(gui_separator,',').split(',') if item]
        sequence_list = [ item.strip() for item in user_input['seqlist'].replace(gui_separator,',').split(',') if item]
        MAKEALIAS = True
        folder_populator( source_folder, destination_folder, main_name, update, shot_list, sequence_list, MAKEALIAS )
        print 'Folder Structure Updated/Copied - OK to quit!'