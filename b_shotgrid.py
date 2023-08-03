import os

import shotgun_api3
from importlib import *
from . import bron_paths

sg = shotgun_api3.Shotgun(#deleted)

entity_fields = dict(Playlist=['versions'],
                     Version=['sg_path_to_movie', 'sg_uploaded_movie', 'code'],
                     Episode=['code', 'id'],
                     Shot=['sg_source_timecode_in', 'sg_handles', 'sg_edit_timecode_in', 'sg_edit_timecode_out',
                           'sg_cut_in', 'sg_cut_out', 'sg_status_list', 'sg_shot_group', 'sg_preroll', 'assets',
                           'code', 'project'],
                     Scene=['shots', 'code'],
                     Asset=['code', 'sg_asset_1', 'sg_asset_type', 'sg_parent', 'sg_ue_skeletonpath'])


# ##------------------------------------------------## #
# Getter Functions
# ##------------------------------------------------## #
def get_pipeline_step(entity_type, shortcode=None, code=None):
    """
    Given some context will query Shotgrid to get a valid pipeline step for an entity

    :param entity_type: (Str) Entity type that we want to query
    :param shortcode: (Str) Short code of the pipeline step
    :param code: (Str) Code for pipeline step
    :return: (PipelineStep) Shotgrid pipeline step data
    """

    # Given a short code and entity type will return a pipeline step if it exists
    step_filter = [['entity_type', 'is', entity_type]]

    # add data depending on what is passed in
    if shortcode:
        step_filter.append(['short_name', 'is', shortcode])
    if code:
        step_filter.append(['code', 'is', code])

    step_fields = ['department', 'short_name']

    steps = sg.find('Step', step_filter, step_fields)

    if len(steps) > 1:
        print('Found multiple steps for {}'.format(shortcode))
        return None
    elif len(steps) == 0:
        print('Could not find any valid steps for {}'.format(shortcode))
        return None
    else:
        return steps[0]


def get_latest_version(entity, step):
    """
    Given an entity and pipeline step will return the next version

    :param entity: (dict) Shotgrid entity that we want to check versions for
    :param step: (dict) Pipeline step entity that we want to use to get version number
    :return: (int) next version number
    """

    # gets the next version number for a step on an entity
    version_filters = [['entity', 'is', entity],
                       ['sg_pipeline_step', 'is', step]]
    version_fields = ['sg_version_number']

    all_versions = sg.find('Version', version_filters, version_fields)
    version_num = 0

    for i in all_versions:
        sg_version_num = i.get('sg_version_number')
        if not sg_version_num:
            continue
        if int(sg_version_num) > version_num: version_num = int(sg_version_num)

    return version_num + 1


def get_entity(prj, entity, name=None, sg_id=None, additional_fields=None, additional_filters=None):
    """
    Gets playlist data given a name or an id

    : project: (str) project code
    : name: (str) name of a playlist to return
    : id (int) id for a playlist
    : additional_fields: (list) additional fields the user wants information back

    :return: (dict) Shotgrid query data for an entity
    """
    if additional_filters is None:
        additional_filters = []
    if additional_fields is None:
        additional_fields = []

    # make sure that either name or id are passed in correctly
    if not name and not sg_id and not additional_filters:
        print(f'No id or name passed in. Cannot find {entity}')
        return None

    # get our fields based on the entity passed in
    sg_fields = entity_fields[entity]

    sg_fields.extend(additional_fields)
    sg_fields = list(set(sg_fields))

    # add our project filter
    sg_filters = [bron_paths.project_filters[prj]]

    # add the name and id filter if appropriate
    if name:
        sg_filters.append(['code', 'is', name])
    if sg_id:
        sg_filters.append(['id', 'is', sg_id])

    sg_filters.extend(additional_filters)

    return sg.find_one(entity, sg_filters, sg_fields)


def get_entities(prj, entity, additional_fields=None, additional_filters=None):
    """
    Given data returns a list of all entities

    : project: (str) project code
    : name: (str) name of a playlist to return
    : id (int) id for a playlist
    : additional_fields: (list) additional fields the user wants information back

    :return: (dict) Shotgrid query data for an entity
    """
    if additional_filters is None:
        additional_filters = []
    if additional_fields is None:
        additional_fields = []

    # get our fields based on the entity passed in
    sg_fields = entity_fields[entity]

    sg_fields.extend(additional_fields)
    sg_fields = list(set(sg_fields))

    # add our project filter
    sg_filters = [bron_paths.project_filters[prj]]
    sg_filters.extend(additional_filters)

    return sg.find(entity, sg_filters, sg_fields)


def get_user(name):
    """

    :param name: (str) The user name used to find the shotgrid user
    :return: (dict) user entity
    """
    # finds human user entity
    user_filter = [['login', 'is', name]]
    user_fields = ['login']
    user = sg.find_one('HumanUser', user_filter, user_fields)

    return user


def get_assets_from_shot(prj, episode, scene, shot):
    """
    Gets all the valid assets for a shot
    :param prj: (str) short code for current project
    :param episode: (int) Episode number
    :param scene: (int) Scene number
    :param shot: (int) Shot number
    :return:
    """

    shot_code = bron_paths.shot_code[prj].format(Episode=episode,
                                                 Scene=scene,
                                                 Shot=shot)

    project = sg.find_one("Project", [["name", "contains", "Gossamer"]], ["name"])
    scene = get_entity(prj, 'Scene', name=str(scene), additional_fields=['assets'])
    shot = sg.find("Shot",
                   [
                       bron_paths.project_filters[prj],
                       ["sg_scene", "is", scene],
                       ["code", "is", shot_code]
                   ],
                   [
                       "assets"
                   ]
                   )
    assets = shot[0]["assets"]

    return assets


# ### ---------------------------------------------------------------------------------------- ###
# ### Update functions


def update_pipeline_step(scene, department):
    """
    Legacy function. Will attempt to update the pipeline step for versions in a scene
    :param scene:
    :param department:
    :return:
    """
    # get the pipeline step that relates to the department
    pipe_step = get_pipeline_step('Shot', code=department)

    # finds all versions and fills in the pipeline step for the version

    # todo: make the project set more generic instead of hard coded
    filters = list(['code', 'is', scene])
    filters.append(bron_paths.project_filters['GS'])

    fields = ['shots']
    scenes = sg.find('Scene', filters, fields)

    if not len(scenes) == 1:
        print('Should only find one scene but found {}'.format(len(scenes)))
        return None

    scene_data = scenes[0]

    for shot in scene_data['shots']:
        version_filter = [['entity', 'is', shot],
                          ['sg_department', 'is', department]]
        version_fields = ['sg_department', 'sg_pipeline_step']

        versions = sg.find('Version', version_filter, version_fields)

        for version in versions:
            if version['sg_pipeline_step'] is None:
                print('No pipeline step found!')
                data = {'sg_pipeline_step': pipe_step}
                sg.update('Version', version['id'], data)


# ### ---------------------------------------------------------------------------------------- ###
# ### Review functions

def download_playlist(prj, name=None, sg_id=None):
    """
    :prj: (str) Project code
    :name: (str) name of playlist to download
    :sg_id: (int) id of project to download)

    """
    # attempt to get the playlist
    playlist = get_entity(prj, 'Playlist', name=name, sg_id=sg_id)

    # if no play list returned then we bail
    if not playlist:
        print(f'Unable to find playlist {name} id: {sg_id}')
        return None

    # go through each version in the playlist
    for vrs in playlist['versions']:

        # get the version data and pull the movie path
        vrs_data = get_entity(prj, 'Version', sg_id=vrs['id'])
        movie_path = vrs_data['sg_path_to_movie']

        # check to see if we already have the movie path downloaded
        if movie_path:
            if not os.path.exists(movie_path):
                print('Cannot find version... Time to download')
                print(movie_path)

                # get the folder path and make sure it exists first
                folder = os.path.dirname(movie_path)
                if not os.path.exists(folder):
                    os.makedirs(folder)

                # get the attachment and download it
                attachment = vrs_data['sg_uploaded_movie']
                sg.download_attachment(attachment['id'], file_path=movie_path)

            else:
                # already exists!!!
                print(f'Version {vrs_data["code"]} already exists ')
