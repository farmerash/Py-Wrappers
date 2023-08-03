import io
import json, pathlib, os, re
from subprocess import Popen, PIPE
from importlib import *

import unreal
import shotgun_api3
from . import bron_paths, bron_shotgrid

reload(bron_paths)
reload(bron_shotgrid)

try:
    from . import bron_characters

    reload(bron_characters)
except:
    # print(f'Failed to load characters module')
    pass

sg = shotgun_api3.shotgun.Shotgun(#Deleted)


# ## Plugin Setting functions
def get_department_data():
    settings = unreal.SceneSetupSettings.get_default_object()
    department_data = settings.get_editor_property('Departments')

    dpt_data = {}
    for i in department_data:
        department = i.get_editor_property('department')
        color = i.get_editor_property('color')

        dpt_data[department] = color

    return dpt_data


def get_departments():
    """
    Returns a list of all the department names
    """
    return get_department_data().keys()


# ## Helper functions
def get_assets_in_folder(folder):
    """
    Gets all the assets from a given folder in Unreal
    """
    # check to see if folder exists
    if not unreal.EditorAssetLibrary.does_directory_exist(folder):
        unreal.log_warning('Could not find folder {}'.format(folder))
        return []

    # Collect all assets
    asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()
    assets = asset_reg.get_assets_by_path(folder)

    return assets


def _run_import_task(import_task):
    """

    function to run the unreal import task
    @note (Jai): Separating this out to a function to possibly enable batching imports
    in the future.

    @param import_task: Unreal Asset Import Task
    @return: None
    """
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([import_task])


def _make_import_task(destination_name, destination_path, full_file_name, options):
    """

    function to setup options for importing something into unreal

    @param destination_name: (str) what to save the file as after importing
    @param destination_path: (str) where to save the file
    @param full_file_name: (str) full name  (with path) of the file to import
    @param options: (created from unreal.FbxImportUI) the options to select for the import task
    @return: Unreal Asset Import Task
    """
    task = unreal.AssetImportTask()
    task.automated = True
    task.destination_name = destination_name
    task.destination_path = destination_path
    task.filename = full_file_name
    task.replace_existing = True
    task.save = True
    task.options = options

    return task


def import_animation_sequence(destination_name, destination_path, full_file_name, skeleton):
    """
    function to import an animation sequence

    @param destination_name: (str) what to save the file as after importing
    @param destination_path: (str) where to save the file
    @param full_file_name: (str) full name  (with path) of the file to import
    @param skeleton: (unreal Skeleton object) the skeleton to attach to the animation
    @return: None
    """
    options = unreal.FbxImportUI()
    options.import_animations = True
    options.skeleton = skeleton

    import_task = _make_import_task(destination_name, destination_path, full_file_name, options)
    _run_import_task(import_task)

    """unreal.log_error("PRINTING ARGS")
    unreal.log_warning("destination_name " + destination_name)
    unreal.log_warning("destination path " + destination_path)
    unreal.log_warning("full_file_name " + full_file_name)
    unreal.log_warning(skeleton)"""


def reimport_animation_sequence(anim_sequence, episode, scene):
    """
    Takes an existing anim sequence, pulls the required data from it and
    triggers import function

    @param anim_sequence: (Unreal Animation Sequence Object): The animation to reimport
    @param episode: (Int): Episode number
    @param scene: (Int): Scene number
    @return: None
    """
    destination_name = anim_sequence.get_name()
    destination_path = anim_sequence.get_path_name().rpartition("/")[0]
    print(destination_path)
    skeleton = anim_sequence.get_editor_property('skeleton')

    anim_import_data = anim_sequence.get_editor_property('asset_import_data')
    file_path = anim_import_data.get_first_filename()

    # clean path
    if "C:/shared/gos/shots" not in file_path:
        end_part = file_path.split("{}/{}".format(episode, scene))[-1]

        file_path = "C:/shared/gos/shots/{}/{}/{}".format(episode, scene, end_part)

    # if we can't find the file for whatever reason log error and move on
    if not os.path.exists(file_path):
        unreal.log_error('Could not find file {} on disk'.format(file_path))
        return
    import_animation_sequence(destination_name, destination_path, file_path, skeleton)



def _create_generic_asset(asset_path="", asset_class=None, asset_factory=None):
    """
    Checks to see if asset exists. Returns existing asset or creates new one and returns that

    @param: (str) asset_path: path to the asset desired
    @param: (class) asset_class: class of the asset we want to create
    @param: (unreal.factory) asset_factory: factory that handles creating the class

    @return (asset): The found or created asset. None if it didnt' work
    """
    print(f'Creating asset: {asset_path}')
    print(f"{unreal.EditorAssetLibrary.does_asset_exist(asset_path)}")
    if not unreal.EditorAssetLibrary.does_asset_exist(asset_path=asset_path):
        path = asset_path.rsplit('/', 1)[0]
        name = asset_path.rsplit('/', 1)[1].split('.')[0]

        dt = unreal.AssetToolsHelpers.get_asset_tools().create_asset(asset_name=name,
                                                                     package_path=path,
                                                                     asset_class=asset_class,
                                                                     factory=asset_factory)
        if not dt:
            unreal.log_error(f'Failed to create asset {asset_path}')
            return None

        unreal.EditorAssetLibrary.save_asset(dt.get_path_name(), True)
        return dt
    return unreal.load_asset(asset_path)


def set_track_eval_preroll(track, eval_preroll) -> None:
    """
    Sets the eval preroll value on a track
    :param track: (unreal.MovieSceneTrack) Track we want to set pre roll on
    :param eval_preroll: (bool) eval_preroll option
    :return: None
    """
    eval_options = track.get_editor_property('eval_options')
    eval_options.set_editor_property('evaluate_in_preroll', eval_preroll)


def update_perforce_folder(user, workspace, folder):
    """
    Attempts to update the perforce folder to the latest

    @param user: (string) User login details for perforce
    @param workspace: (string) Root folder for perforce workspace
    """
    try:
        from p4_api import p4_handler
    except Exception as e:
        unreal.log_error("Unreal not launched with launcher. Cannot update perforce to latest. Please make sure"
                         "that files up up to date!!!")
        return

    # instantiate
    handler = p4_handler.P4Handler(user)
    # select the workspace
    handler.set_client_name(workspace)

    # sync
    try:
        handler.sync(file_path="{}/...".format(folder))
    except Exception as e:
        # unreal.log('Folder already up to date!')
        unreal.log_error(e)


# ## Classes
class BronSequence:
    object = None
    asset = None

    name = None
    sequence_path = ""

    _asset = None
    _world = None

    def __init__(self):
        pass

    # ---- Properties
    @property
    def world(self):
        return self._world

    @property
    def exists(self):
        return unreal.EditorAssetLibrary.does_asset_exist(self.sequence_path)

    @property
    def asset(self):
        """
        Returns sequence asset or tries to load it if we don't have it already
        """
        if not self._asset:
            # if our sequence path is an asset try and load it
            if self.exists:
                self._asset = unreal.load_asset(self.sequence_path)
            else:
                self._asset = None

        return self._asset

    @asset.setter
    def asset(self, asset):
        # todo: validate incoming asset is a level sequence asset
        print(f'Setting asset {asset}')
        self._asset = asset

    # ---- Function
    def load(self, load_level=False):
        """
        Load the shot sequence

        @param load_level: {bool} Whether we should load the level as well or just the sequence
        """
        # if directed open the level first
        if load_level:
            editor_world = unreal.EditorLevelLibrary.get_editor_world().get_path_name().split(".")[0]
            if self.world:
                if not editor_world == self.world:
                    levelEditorSubsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
                    levelEditorSubsystem.load_level(self.world)

        # open level sequence
        unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(self.asset)


class BronSceneSequence(BronSequence):
    _sg_data = None
    _sg_shots = None

    shot_data = {}

    _world = None

    # context
    episode = None
    scene = None
    project = None

    def __init__(self, episode=None, scene=None, project=None):
        super().__init__()

        # set up context
        self.episode = episode
        self.scene = scene
        self.project = project

        self.initialize()

    def initialize(self):
        """
        Initializes this sequence
        """
        # make sure that we have a context
        if self.episode is None or self.scene is None:
            unreal.log_error('Context invalid. Please provide an episode and a scene')
            return None

        # --- Sequence asset setup
        self.name = bron_paths.scene_name[self.project].format(Project=self.project,
                                                               Episode=self.episode,
                                                               Scene=self.scene)

        self.sequence_path = bron_paths.scene_sequence[self.project].format(Project=self.project,
                                                                            Episode=self.episode,
                                                                            Scene=self.scene,
                                                                            SceneName=self.name)

    # ------ Properties
    @property
    def data(self):
        """
        Returns a dictionary of data to be used in formating paths
        """

        return dict(Project=self.project,
                    Episode=self.episode,
                    Scene=self.scene)

    @property
    def shots(self):
        """
        Returns a list of all the shots in this scene from Shotgrid data
        """
        shots = []
        valid_ids = []

        for shot in self.sg_shots:
            valid_ids.append(shot['id'])

        for shot in self.sg_data['shots']:
            if shot['id'] in valid_ids:
                shot_num = int(shot['name'].rsplit('_', 1)[-1])
                shots.append(shot_num)

        return shots

    @property
    def ue_frame_rate(self):
        # make sure that the display rate is set correctly
        return unreal.FrameRate(numerator=self.frame_rate)

    @property
    def frame_rate(self):
        obj = unreal.SceneSetupSettings.get_default_object()
        return obj.get_editor_property('FrameRate')

    @property
    def world(self):
        """
        Given the context we should be able to find what world should be used

        @return None
        """
        print("working here")
        # if we already have a handle on the world return that
        if self._world:
            return self._world

        # if not we need to find it
        else:
            world_path = bron_paths.world_scene_path[self.project].format_map(self.data)

            # make sure that the asset exists, if it does load it
            if not unreal.EditorAssetLibrary.does_asset_exist(world_path):
                unreal.log_warning(f'Unable to find scene world: {world_path}')
                self._world = None
            else:
                self._world = world_path

            return self._world

    @property
    def sg_data(self):
        """
        Updates shotgrid data for the scene
        :return: (dict) shotgrid scene entity
        """
        if not self._sg_data:
            self._sg_data = bron_shotgrid.get_entity(self.project, 'Scene', name=str(self.scene))

        return self._sg_data

    @property
    def sg_shots(self):
        """
        Gets a list of all shots connected to this scene
        """
        # if we don't have a list of shots from shotgrid go find information
        if not self._sg_shots:
            filters = [['sg_scene', 'is', {'type': "Scene", 'id': self.sg_data['id']}],
                       ['sg_status_list', 'is_not', "omt"]]

            # self._sg_shots = sg.find('Shot', filters, fields)
            self._sg_shots = bron_shotgrid.get_entities(self.project, 'Shot', additional_filters=filters)

        # return shotgrid query results
        return self._sg_shots

    @property
    def ue_shot(self):
        """
        Checks the scene sequence to see what shots are available

        @return list(Sections): List of all the shot sections on
        """
        shot_data = {}
        sections = []
        # get the master shots track, if we can't find it bail
        master_tracks = self.asset.find_master_tracks_by_type(unreal.MovieSceneCinematicShotTrack)

        if not master_tracks:
            unreal.log_warning(f'Could not find master track for {self.name}')
            return {}

        # get the sections, if none then bail
        for track in master_tracks:
            sections = track.get_sections()

            if not sections:
                unreal.log_warning(f'Could not find any sections for {self.name}')
                return {}

        for section in sections:
            # write up an error report for users but don't stop them opening the scene
            if not section.get_sequence():
                unreal.log_warning('Found a section with no sequence attached. Please check shot sections!!!')
                continue

            shot_name = section.get_sequence().get_name()

            # todo: properly split shot name up into bits using templates
            episode_code = int(shot_name.split('_')[0][2:])
            scene_code = int(shot_name.split('_')[1])
            shot_code = int(shot_name.split('_')[2])

            if not episode_code == self.episode:
                unreal.log_warning('Shot does not match scene episode: {}'.format(shot_name))
                continue
            if not scene_code == self.scene:
                unreal.log_warning("Shot does not")

            # shot = BronShotSequence(self.episode, self.scene, shot_code)
            # shot.section = section
            data = dict(episode=episode_code,
                        scene=scene_code,
                        shot=shot_code,
                        section=section)

            shot_data[shot_code] = data

        return shot_data

    # ------ Callable functions
    def update(self):
        """
        Will update the scene sequence to follow current data from shotgrid
        """
        # first lets make sure that we have a valid scene sequence and if not
        # lets create one

        if not self.asset:
            self.asset = _create_generic_asset(asset_path=self.sequence_path,
                                               asset_class=unreal.LevelSequence,
                                               asset_factory=unreal.LevelSequenceFactoryNew())

            print(f'Does asset exist: {unreal.EditorAssetLibrary.does_asset_exist(self.sequence_path)}')
            print(f'Asset: {self.asset}')

            if not self.asset:
                unreal.log_warning(f"Unable to load {self.sequence_path}")
                return

        # make sure that the display rate is set correctly
        self.asset.set_display_rate(self.ue_frame_rate)

        # setup extremes to work back from
        in_frame = 99999999999999999
        out_frame = 0

        # make sure we have a handle to a valid shot track
        master_tracks = self.asset.find_master_tracks_by_type(unreal.MovieSceneCinematicShotTrack)
        if not master_tracks:
            track = self.asset.add_master_track(unreal.MovieSceneCinematicShotTrack)
        else:
            # todo: make sure we have one track and not multiple ones
            track = master_tracks[0]

        # # go through all valid shots and update/create them in the scene sequence
        updated_shots = []
        for shot in self.sg_shots:
            shot_num = int(shot['code'].split('_')[-1])

            unreal.log(shot_num)
            if shot_num in self.ue_shot:
                section = self.ue_shot[shot_num]['section']

            else:
                unreal.log('Shot not in master scene sequence')
                bron_shot = BronShotSequence(self.episode, self.scene, shot_num, self.project)
                if not bron_shot.exists:
                    unreal.log_warning(f"Shot {bron_shot.name} does not exist as an asset")
                    continue
                else:
                    unreal.log(f"# ##---------------- {bron_shot.name}")

                section = track.add_section()
                bron_shot.section = section

                section.set_sequence(bron_shot.asset)

            start_frame = round(shot['sg_edit_timecode_in'] * (self.frame_rate * 0.001))
            end_frame = round(shot['sg_edit_timecode_out'] * (self.frame_rate * 0.001))

            # set start and end frame. Make sure that we set them in the correct order
            if start_frame > section.get_end_frame():
                section.set_end_frame(end_frame)
                section.set_start_frame(start_frame)
            else:
                section.set_start_frame(start_frame)
                section.set_end_frame(end_frame)

            # make sure the handles is set correctly
            params = section.get_editor_property('parameters')
            start_frame_offset = params.start_frame_offset
            start_frame_offset.value = shot['sg_handles'] * 1000

            # check global in and out and update if required
            if start_frame < in_frame:
                in_frame = start_frame

            if end_frame > out_frame:
                out_frame = end_frame

        # sets frame ranges
        self.asset.set_playback_start(in_frame)
        self.asset.set_playback_end(out_frame)

        self.asset.set_view_range_start((in_frame - 20) / 24)
        self.asset.set_view_range_end((out_frame + 20) / 24)

        unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()

    # ## Helper functions
    def get_shot(self, shot_num):
        """
        Given a shot number returns a shot object
        """
        return BronShotSequence(self.episode, self.scene, shot_num, self.project)


class BronShotSequence(BronSequence):
    scene_sequence = None

    section = None

    audio_track = None

    # context
    episode = None
    scene = None
    shot = None

    # properties
    _animation_folder = None
    _audio_folder = None
    _world = None
    _scene_world = None

    _camera = None
    _subscene_track = None
    _override_track = None
    _subscenes = {}

    # shotgrid data
    _sg_data = {}

    # perforce
    _user = None

    _root_import_folder = "C:/shared/gos/shots"

    def __init__(self, episode, scene, shot, project):
        super().__init__()

        self.project = project

        self.episode = episode
        self.scene = scene
        self.shot = shot

        self.initialize()

    def initialize(self):
        """
        Initializes this sequence class by finding the shot sequence for the context given
        """
        # from the context create the sequence path that we should expect and load sequence object
        self.name = bron_paths.shot_name[self.project].format(Project=self.project,
                                                              Episode=self.episode,
                                                              Scene=self.scene,
                                                              Shot=self.shot,
                                                              ArtistVersion=1)

        self.sequence_path = bron_paths.shot_sequence[self.project].format(Project=self.project,
                                                                           Episode=self.episode,
                                                                           Scene=self.scene,
                                                                           Shot=self.shot,
                                                                           ArtistVersion=1)

    # ------ Properties
    @property
    def data(self):
        """
        Returns a dictionary of data to be used in formating paths
        """
        return dict(Project=self.project,
                    Episode=self.episode,
                    Scene=self.scene,
                    Shot=self.shot)

    @property
    def frame_rate(self):
        # make sure that the display rate is set correctly
        obj = unreal.SceneSetupSettings.get_default_object()
        frame_rate = obj.get_editor_property('FrameRate')

        return unreal.FrameRate(numerator=frame_rate)

    @property
    def sg_data(self):
        """
        Gets the shotgrid data for this shot context
        :return: (dict) Shotgrid query for a shot
        """
        # if we don't already have the data then we need to get it
        if not self._sg_data:
            self._sg_data = bron_shotgrid.get_entity(self.project,
                                                     'Shot',
                                                     name=self.name)

        return self._sg_data

    @property
    def user(self):
        """
        Holds the current user to use for perforce updates
        :return: (str) User name for perforce login
        """
        # todo: want to tie this into Shotgrid user details?

        if not self._user:
            # if not check to see if env variable has been set and use that
            if 'P4USER' in os.environ:
                self._user = os.environ['P4USER']

        return self._user

    @user.setter
    def user(self, name=''):
        """
        Sets the user name based on the input
        """
        # if a name gets passed in then use that
        self._user = name

    @property
    def animation_folder(self):
        """
        If we have the animation folder stored it will return that, otherwise it will
        find it (or create it) and return the path
        """
        # todo: update to generic workflow
        # if self._animation_folder:
        #     return self._animation_folder
        # else:
        #     # make sure that we have an animation folder
        #     shot_folder = "/Game/EP{:03d}/PHASE03_post/{:03d}/{:04d}/".format(self.episode,
        #                                                                       self.scene,
        #                                                                       self.shot)
        #
        #     animation_folder = shot_folder + "animation"
        #     if not unreal.EditorAssetLibrary.does_directory_exist(animation_folder):
        #         animation_folder = shot_folder + "animations"
        #         if not unreal.EditorAssetLibrary.does_directory_exist(animation_folder):
        #             unreal.log_warning('Could not find animation folder. Creating one')
        #             unreal.EditorAssetLibrary.make_directory(animation_folder)
        #
        #     self._animation_folder = animation_folder
        #     return self._animation_folder

        return ""

    @property
    def audio_folder(self):
        """
        If we have the audio folder stored it will return that, otherwise it will
        find it (or create it) and return the path
        """
        # todo: update to generic workflow
        # if not self._audio_folder:
        #     shot_folder = "/Game/EP{:03d}/PHASE03_post/{:03d}/{:04d}/".format(self.episode,
        #                                                                       self.scene,
        #                                                                       self.shot)
        #
        #     audio_folder = shot_folder + "audio"
        #
        #     if not unreal.EditorAssetLibrary.does_directory_exist(audio_folder):
        #         unreal.log('Could not find audio folder. Creating one')
        #         unreal.EditorAssetLibrary.make_directory(audio_folder)
        #
        #     self._audio_folder = audio_folder
        #
        # return self._audio_folder
        return ""

    @property
    def shot_level_path(self):
        """
        Returns the expected path to the shot override level
        """
        return bron_paths.world_shot_path[self.project].format_map(self.data)

    @property
    def scene_level_path(self):
        """
        Returns the expected path to the shot override level
        """
        return bron_paths.world_scene_path[self.project].format_map(self.data)

    @property
    def world(self):
        """
        Given the context we should be able to find what world should be used

        @return None
        """
        # if we don't already have a world then we want to find one
        if not self._world:
            # first look to see if we can get the shot level
            world_path = self.shot_level_path

            # check to see if the asset exists, if it does load it if not look to the scene
            if not unreal.EditorAssetLibrary.does_asset_exist(world_path):
                unreal.log_warning(f"Unable to find shot world {world_path}. Looking for scene world")
                world_path = self.scene_level_path

            self._world = world_path

            # if the asset path is valid load the world
            if not unreal.EditorAssetLibrary.does_asset_exist(world_path):
                unreal.log_warning(f"Unable to find scene world {world_path}")
                self._world = None
                return self._world

        # return world
        return self._world

    @property
    def camera(self):
        """
        Returns the camera object for this shot
        """
        if not self._camera:
            self._camera = BronCamera(self)

        return self._camera

    @property
    def folders(self):
        """
        Returns a list of folders in the sequence in a dictionary

        :returns: (dict) Dictionary with key name of folder and pair the folder obj
        """
        folders = {}
        for folder in self.asset.get_root_folders_in_sequence():
            folders[str(folder.get_folder_name())] = folder

        return folders

    # @property
    # def subscene_track(self):
    #     """
    #     Returns the subscene track if it exists
    #     """
    #     # todo: remove, obsolete in new format
    #
    #     if self._subscene_track:
    #         return self._subscene_track
    #
    #     self._subscene_track = self._get_subscene_track('Subscenes')
    #     return self._subscene_track

    @property
    def subscenes(self):
        """
        Returns a list of subscenes
        """
        # if the dict has already been filled in then return it
        if self._subscenes:
            return self._subscenes

        self._subscenes = {}

        for dpt_tag in self.folders:
            tracks = self.folders[dpt_tag].get_child_master_tracks()

            for track in tracks:
                if "Shot" in str(track.get_editor_property('display_name')):
                    # todo: Make sure we only have one section...
                    section = track.get_sections()[0]
                    sequence = section.get_sequence()

                    self._subscenes[dpt_tag] = dict(name=dpt_tag,
                                                    section=section,
                                                    sequence=sequence)

        return self._subscenes

    @property
    def start(self):
        """
        Returns start frame
        """
        return self.asset.get_playback_start()

    @property
    def end(self):
        """
        Returns the end frame
        """
        return self.asset.get_playback_end()

    @property
    def source_offset(self) -> int:
        """
        Calculates the frame offset to get this shot timecode back to source
        :return: (int) frame offset to get back to source timecode
        """
        source_in = (self.sg_data['sg_source_timecode_in'] * 0.001) * 24
        first_frame = self.start + self.sg_data['sg_handles']

        return int(source_in - first_frame)

    @property
    def is_valid(self):
        """
        Returns if this shot is valid shot to work on from Shotgrid data
        """
        if self.sg_data['sg_status_list'] == 'omt':
            return False
        else:
            return True

    @property
    def display_rate(self):
        """
        Returns unreal display rate object as defined in the project plugin settings
        :return: (unreal.FrameRate)
        """
        obj = unreal.SceneSetupSettings.get_default_object()
        return unreal.FrameRate(numerator=obj.get_editor_property('FrameRate'))

    @property
    def render_settings(self):
        """
        Returns a render settings data asset object based on what is available
        """
        render_settings_path = bron_paths.render_settings_shot[self.project].format_map(self.data)

        if not unreal.EditorAssetLibrary.does_asset_exist(render_settings_path):
            render_settings_path = bron_paths.render_settings_scene[self.project].format_map(self.data)

            if not unreal.EditorAssetLibrary.does_asset_exist(render_settings_path):
                unreal.log_warning(f'Unable to find render settings for {self.name}')
                return None

        return unreal.load_asset(render_settings_path)

    @property
    def cvar_look_overrides(self):
        """
        Returns dictionary of cvar overrides for this context
        """
        cvars = {}
        settings = [unreal.SceneSetupSettings.get_default_object(),
                    unreal.load_asset(bron_paths.render_settings_scene[self.project].format_map(self.data)),
                    unreal.load_asset(bron_paths.render_settings_shot[self.project].format_map(self.data))]

        for setting in settings:
            cvars.update(self._get_cvar_overrides(setting, "ConsoleVariables", False))

        return cvars

    @property
    def cvar_quality_overrides(self):
        """
        Returns dictionary of cvar overrides for this context
        """
        cvars = {}
        settings = [unreal.SceneSetupSettings.get_default_object(),
                    unreal.load_asset(bron_paths.render_settings_scene[self.project].format_map(self.data)),
                    unreal.load_asset(bron_paths.render_settings_shot[self.project].format_map(self.data))]

        for setting in settings:
            cvars.update(self._get_cvar_overrides(setting, "ConsoleVariables", True))

        return cvars

    # #########################
    # ------- Helper functions
    @staticmethod
    def _get_cvar_overrides(settings, parameter, quality=False):
        """
        Given a key will look to get the overrides for that parameter

        """
        # just return empty dict if no settings passed in
        if not settings:
            return {}

        data = {}

        look_settings = settings.get_editor_property("LookOverrides")
        if look_settings.get_editor_property(f"bOverride_{parameter}"):
            data.update(look_settings.get_editor_property(parameter))
        if quality:
            quality_settings = settings.get_editor_property("QualityOverrides")
            if quality_settings.get_editor_property(f"bOverride_{parameter}"):
                data.update(quality_settings.get_editor_property(parameter))

        return data

    @staticmethod
    def _update_perforce(dpt='anim'):
        """
        Updates perforce folder
        """
        # todo: old logic that needs to be updated to new pathing and generic workflow
        """
        if not self.user:
            unreal.log_error('No user has been set. Perforce not updated!!!')
            return

        # get the animation publish folder
        shots_sym_folder = "C:/shared/gos/shots/"

        p4v_root_folder = None

        # see if we can resolve the path to its actual location so we can update perforce
        with Popen("fsutil reparsepoint query \"{}\"".format(shots_sym_folder), stdout=PIPE, bufsize=1,
                   universal_newlines=True) as p:
            for line in p.stdout:
                if 'Print Name:' in line:
                    p4v_root_folder = line.split('Print Name:')[-1].lstrip(' ').rstrip('\n')

        # if it didn't resolve then gracefully error
        if p4v_root_folder is None:
            unreal.log_error('Perforce not updated. Could not resolve link: {}'.format(shots_sym_folder))
            return

        workspace = p4v_root_folder.rpartition('\\')[-1]
        folder = self._get_import_folder(root=p4v_root_folder.replace('\\', '/'), dpt=dpt)

        print(f"Folder to update is: {folder}")

        # todo: Currently if the folder hasn't been pulled oown there it will not create it
        #       folder needs to exists before it can be updated
        if not os.path.exists(p4v_root_folder):
            unreal.log_error('Perforce not updated. Path {} is invalid. Check Perforce!!!'.format(folder))
            return

        # update_perforce_folder(self.user, workspace, folder)
        """
        return None

    @staticmethod
    def _get_import_folder(root=None, dpt='anim'):
        """
        Gets the import folder given the base root to work from
        """
        # todo: old logic that needs to be updated to new pathing and generic workflow
        """
        if root is None:
            root = self._root_import_folder

        if dpt == 'anim':
            additional_path = "publish/animation"
        elif dpt == 'audio':
            additional_path = "resources/audio"
        else:
            unreal.log_error(f'Unable to resolve import folder for {dpt}')
            return None

        return f"{root}/{self.episode:03d}/{self.scene:03d}/{self.shot:04d}/{additional_path}"
        """
        return ""

    @staticmethod
    def _get_dpt_tag(dpt):
        """
        Given the department will return the dpt tag as established in Project settings

        :return: (str) department tag setup from project settings
        """
        dpt_tag = None

        # get project settings and go through to see if we find a match
        settings = unreal.SceneSetupSettings.get_default_object()
        department_data = settings.get_editor_property('Departments')
        for i in department_data:
            tag = i.get_editor_property('dpt_tag')
            if tag == dpt:
                if dpt_tag:
                    unreal.log_warning(f'Found more than one setting for dpt {dpt.name}')
                    return None
                else:
                    dpt_tag = i.get_editor_property('department')

        return dpt_tag

    def _resolve_template(self, template, additional_data=None):
        """
        Given a template will attempt to resolve and pass back valid path

        :param template: (str) string object ready to be formatted
        :param additional_data: (dict) Dictionary of additional data to help resolve the template
        :return: (str) resolved template string
        """
        if additional_data is None:
            additional_data = {}

        data = dict(Project=self.project,
                    Episode=self.episode,
                    Scene=self.scene,
                    Shot=self.shot,
                    Name=self.name)

        data.update(additional_data)

        return template[self.project].format_map(data)

    def _get_subscene_track(self, track_name):
        """
        Searches for a specific track within the sequence. If it can't find specified track will create
        it and return the new track
        """
        # get the subscene track
        tracks = self.asset.find_master_tracks_by_type(unreal.MovieSceneSubTrack)

        if "Grp" in track_name:
            dptTag = track_name.split('_')[0]
            track_name = f"{dptTag}_Grp"

        # make sure that we only have one
        if not len(tracks) == 0:
            for track in tracks:
                if track.get_editor_property('display_name') == track_name:
                    return track

        track = self.asset.add_master_track(unreal.MovieSceneSubTrack)
        track.set_editor_property('display_name', track_name)

        return track

    @staticmethod
    def _get_subscene_sections(track):
        """
        Gets all sections for a particular track

        :param track:
        """
        sections = track.get_sections()

        subsections = []

        for section in sections:
            if section.__class__ == unreal.MovieSceneSubSection:
                sequence = section.get_sequence()
                subsections.append(dict(section=section, sequence=sequence))

        return subsections

    def _get_override_sequences(self):
        """
        Gets a list of all the subsequences for this context

        :return: (dict) Dictionary of all the override seqeunces for this context and data on that override
        """
        # get the override folder path
        override_path = self._resolve_template(bron_paths.override_folder)
        assets = unreal.EditorAssetLibrary.list_assets(override_path)

        override_sequences = {}

        data = dict(Project=self.project,
                    Episode=self.episode,
                    Scene=self.scene,
                    Shot=self.shot,
                    Name=self.name)

        # go through all the assets from our override sequence folder and check to see if
        # we have any scene overrides or group overrides that match shotgrid data
        unreal.log("Going through possible assets....")
        for i in assets:
            override_name = i.split('.')[-1]
            regex = bron_paths.create_regex(bron_paths.override_name[self.project],
                                            self.project,
                                            data)
            match = regex.match(override_name)
            if match:
                # if match is a scene override check
                if 'Scene' in match.group('Group') or 'Scn' in match.group('Group'):
                    print(f'We have a valid override! {override_name}')
                    index = 0
                    color_factor = 0.7

                # if a group override check
                elif f"Grp{self.sg_data['sg_shot_group']}" in match.group('Group'):
                    grpTag = match.group('Group').replace('Grp', '')
                    if not grpTag == self.sg_data['sg_shot_group']:
                        continue
                    print(f"We have a valid group override")

                    index = 1
                    color_factor = 0.85
                # anything else ignore
                else:
                    continue

                # get dpt
                dpt = match.group("Dept")

                dpt_data = []
                if dpt in override_sequences.keys():
                    dpt_data = override_sequences[dpt]

                dpt_data.append(dict(asset=i,
                                     dpt=dpt,
                                     Group=match.group("Group"),
                                     index=index,
                                     color_factor=color_factor))

                override_sequences[dpt] = dpt_data

        return override_sequences

    def _setup_folders(self):
        """
        Setup the folder structure for the sequence
        """
        subs = get_departments()
        dpt_data = get_department_data()

        folders = self.folders

        for i in subs:
            if i not in folders:
                unreal.log(f"Cannot find folder for {i}. Creating one!")
                folder = self.asset.add_root_folder_to_sequence(i)
                folder.set_folder_color(dpt_data[i])

    def _setup_subscenes(self) -> None:
        """
        Will go through the master track and set up all the sub scenes appropriately
        :return:
        """
        # todo: potentially pull this out into generic function
        row_index = 2

        folders = self.folders

        for sub in get_departments():
            # if we can't find a subscene based on our keys then we need to create one
            master_track = self._get_subscene_track(f"{sub}_Shot")

            if not master_track:
                master_track = self.asset.add_master_track(unreal.MovieSceneSubTrack)
                master_track.set_editor_property('display_name', f"{sub}_Shot")

            if not sub in folders:
                unreal.log_warning(f'Unable to locate folder for {sub}')
            else:
                folders[sub].add_child_master_track(master_track)

            master_track.set_sorting_order(row_index)

            master_track.set_color_tint(get_department_data()[sub])
            set_track_eval_preroll(master_track, True)

            # once we have a track check to see if we have the shot section
            section = None

            subscene_data = dict(Project=self.project,
                                 Episode=self.episode,
                                 Scene=self.scene,
                                 Shot=self.shot,
                                 Dpt=sub)

            sequence_path = bron_paths.sub_sequence[self.project].format_map(subscene_data)

            # go through all sections and check to see if what we want already exists
            sections = self._get_subscene_sections(master_track)

            for i in sections:
                if sequence_path == i['sequence'].get_path_name():
                    section = i['section']
                    subscene = i['sequence']

            if not section:
                # if it already exists then load it, otherwise create it
                if unreal.EditorAssetLibrary().does_asset_exist(sequence_path):
                    subscene = unreal.load_asset(sequence_path)
                else:
                    subscene = _create_generic_asset(asset_path=sequence_path,
                                                     asset_class=unreal.LevelSequence,
                                                     asset_factory=unreal.LevelSequenceFactoryNew())

                if not subscene:
                    unreal.log_warning(f'Unable to find or create subscene for {sub}')
                    continue

                # create blank section as we don't have it yet
                section = None

            # make sure the display rate is correct
            subscene.set_display_rate(self.display_rate)
            subscene.set_playback_start(self.start - self.sg_data['sg_preroll'])
            subscene.set_playback_end(self.end)

            subscene.set_view_range_start((self.start - self.sg_data['sg_preroll'] - 10) / 24)
            subscene.set_view_range_end((self.end + 10) / 24)

            # if we don't have a section then we need to create one
            if not section:
                section = master_track.add_section()
                section.set_sequence(subscene)

            # set section values
            section.set_end_frame(self.end)
            section.set_start_frame(self.start - self.sg_data['sg_preroll'])

            # section.set_editor_property('pre_roll_frames', unreal.FrameNumber(self.sg_data['sg_preroll'] * 1000))

            # todo: do we need this?
            # params = section.get_editor_property('parameters')
            # params.start_frame_offset = unreal.FrameNumber(self.sg_data['sg_preroll'] * 1000)
        return None

    def _setup_overrides(self):
        """
        Will look for overrides for the shot context and set them up
        :return: None
        """
        print(f"setting up overrides for {self.name}")
        if not self.asset:
            unreal.log_warning(f"Shot sequence for {self.name} has not been generated. Create this first and try again")
            return

        override_sequences = self._get_override_sequences()
        # if we don't find any overrides bail
        if not override_sequences:
            unreal.log_warning(f'Failed to find any scene overrides')
            return

        folders = self.folders

        dpts = get_departments()

        # go through all our depts and add in the overrides
        for dpt in override_sequences.keys():

            # make sure what ever we have is something that lines up with what we expect
            if dpt not in dpts:
                unreal.log_warning(f"{dpt} is an invalid department!")
                continue

            for override_sequence in override_sequences[dpt]:
                unreal.log(override_sequence)
                unreal.log(f"{dpt}_{override_sequence['Group']}")
                master_track = self._get_subscene_track(f"{dpt}_{override_sequence['Group']}")

                master_track.set_sorting_order(override_sequence['index'])

                if dpt in folders:
                    folders[dpt].add_child_master_track(master_track)
                else:
                    unreal.log_warning(f'Unable to locate folder for {dpt}')

                base_tint = get_department_data()[dpt]

                track_tint = unreal.Color(r=base_tint.r * override_sequence['color_factor'],
                                          g=base_tint.g * override_sequence['color_factor'],
                                          b=base_tint.b * override_sequence['color_factor'],
                                          a=base_tint.a)

                master_track.set_color_tint(track_tint)
                set_track_eval_preroll(master_track, True)

                section = None
                sections = self._get_subscene_sections(master_track)

                for i in sections:
                    if override_sequence["asset"] == i['sequence'].get_path_name():
                        section = i

                if not section:
                    # create the section and set the level sequence on the section
                    asset = unreal.load_asset(override_sequence['asset'])

                    section = dict()
                    section['section'] = master_track.add_section()
                    section['section'].set_sequence(asset)

                    section['sequence'] = asset

                section['section'].set_row_index(override_sequence['index'])

                # set start and end
                section['section'].set_end_frame(self.end)
                section['section'].set_start_frame(self.start - self.sg_data['sg_preroll'])

                # set hierarchy
                params = section['section'].parameters

                if 'Grp' in override_sequence['Group']:
                    params.set_editor_property('hierarchical_bias', 50)
                else:
                    params.set_editor_property('hierarchical_bias', 1)

                # set the offset so the sequence starts at the right time
                frame_offset = round((self.sg_data['sg_edit_timecode_in'] * 0.001) * 24) - \
                               self.sg_data['sg_handles'] - self.sg_data['sg_preroll']
                start_offset = frame_offset - section['sequence'].get_playback_start()
                frame_number = unreal.FrameNumber(start_offset * 1000)

                params.set_editor_property('start_frame_offset', frame_number)

        # refresh open sequence so changes take effect
        unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()

    def _setup_camera(self) -> None:
        """
        Analysis the sequence and creates/updates camera accordingly
        :return: None
        """
        print("###--- Setting up camera --------------------------------###")
        self._camera = BronCamera(self)

        # get the camera cut track or make it if it doesn't exist
        tracks = self.asset.find_master_tracks_by_type(unreal.MovieSceneCameraCutTrack)
        if tracks:
            if len(tracks) == 1:
                camera_track = tracks[0]
            else:
                unreal.log_warning(f'Found {len(tracks)} camera tracks. Not sure what to do')
                return
        else:
            camera_track = self.asset.add_master_track(unreal.MovieSceneCameraCutTrack)

        set_track_eval_preroll(camera_track, True)

        # get the camera cut section (should be 1 if any) and if none create one
        sections = camera_track.get_sections()
        if sections:
            if len(sections) == 1:
                camera_section = sections[0]
            else:
                unreal.log_warning(f'Found {len(sections)} sections. Not sure what to do')
                return
        else:
            camera_section = camera_track.add_section()

        # set in and out frame (make it a lot more than the sequence to help with preroll)
        camera_section.set_end_frame(self.end + self.sg_data['sg_preroll'])
        camera_section.set_start_frame(self.start - self.sg_data['sg_preroll'])

        # set camera binding
        camera_section.set_camera_binding_id(self.camera.binding.get_binding_id())

    # #########################
    # ------- Update functions
    def update(self, create=True) -> None:
        """
        Updates the sequence for this shot context

        :param create: (bool) If the sequence doesn't exist do we want to create it?
        :return:
        """
        unreal.log('Update shot sequence')

        # if asset doesn't exist at all we want to create it
        if not self.asset and create:
            unreal.log('### Could not find shot. Creating it!')
            self.asset = _create_generic_asset(asset_path=self.sequence_path,
                                               asset_class=unreal.LevelSequence,
                                               asset_factory=unreal.LevelSequenceFactoryNew())

            if self.asset is None:
                unreal.log_error(f'Unable to create shot for {self.name}')
                return

        # first we always want to make sure we ware working in 24fps
        self.asset.set_display_rate(self.frame_rate)

        # calculate start and end frames and set sequence with this values
        start_frame = self.sg_data['sg_cut_in'] - self.sg_data['sg_handles']
        end_frame = self.sg_data['sg_cut_out'] + self.sg_data['sg_handles']

        self.asset.set_playback_start(start_frame)
        self.asset.set_playback_end(end_frame)

        if not self.sg_data['sg_preroll']:
            self.sg_data['sg_preroll'] = 0

        # set the viewport appropriately as well
        self.asset.set_view_range_start((start_frame - self.sg_data['sg_preroll'] - 10) / 24)
        self.asset.set_view_range_end((end_frame + 10) / 24)

        # setup sections of the sequence
        self._setup_folders()
        self._setup_subscenes()
        self._setup_camera()
        self._setup_overrides()

        # save asset and update current sequence
        unreal.EditorAssetLibrary.save_loaded_asset(self.asset, True)
        unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()

    def update_shotgrid_data(self):
        """
        Nullifies the sg data and refreshes it
        """
        self._sg_data = {}
        return self.sg_data

    def update_shot_animations(self):
        """
        Updates all the the animation files and the camera
        """
        # todo: need to update to use new methods and generic workflow
        # update perforce
        # self._update_perforce()
        #
        # self.import_animations()
        # self.reimport_camera()
        return

    def update_audio(self):
        """
        Updates the scene with the audio tracks
        """
        # todo: need to update to use new methods and generic workflow

        # self.audio_track = None
        # audio_section = None
        #
        # # check to see if we have a audio track first
        # for i in self.asset.find_master_tracks_by_type(unreal.MovieSceneAudioTrack):
        #     if not self.audio_track:
        #         self.audio_track = i
        #
        #         # if we have a track see if we can get a singular section
        #         if not audio_section:
        #             sections = self.audio_track.get_sections()
        #
        #             if len(sections) == 0:
        #                 unreal.log('Did not find any sections...')
        #             elif len(sections) > 1:
        #                 unreal.log_warning(f'Found multiple sections for {self.asset.asset_name}. Bailing gracefully')
        #                 return
        #             else:
        #                 audio_section = sections[0]
        #     else:
        #         unreal.log_warning(f'Found more than one Audio Track. Not sure what to do....')
        #         return
        #
        # # if no track found create one
        # if not self.audio_track:
        #     self.audio_track = self.asset.add_master_track(unreal.MovieSceneAudioTrack)
        #     self.audio_track.set_display_name('Audio')
        #
        # # if no section create one
        # if not audio_section:
        #     audio_section = self.audio_track.add_section()
        #
        # # make sure we have the audio file imported and updated
        # self.import_audio()
        #
        # # todo: We can probably check the length of the audio clip against these values
        # #       to determine if the audio file is out of sync or not
        # # set the in and out points of the audio
        # audio_section.set_end_frame(self.sg_data['sg_cut_out'])
        # audio_section.set_start_frame(self.sg_data['sg_cut_in'])
        #
        # # get a link to the audio file we expect
        # audio_file_name = f"SW_{self.episode}_{self.scene}_{self.shot:04d}"
        # audio_full_path = self.audio_folder + "/" + audio_file_name
        #
        # # if we can find it the associate with the section
        # if unreal.EditorAssetLibrary.does_asset_exist(audio_full_path):
        #     audio_asset = unreal.load_asset(audio_full_path)
        #     audio_section.set_sound(audio_asset)
        #
        # unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()
        #
        # eval_options = self.audio_track.get_editor_property('eval_options')
        # eval_options.set_editor_property('evaluate_in_preroll', True)
        return

    def set_look_cvars(self):
        """
        Gets the shot look cvars and then runs them
        """
        overrides = self.cvar_look_overrides
        for i in overrides:
            cmd = f"{i} {overrides[i]}"
            unreal.BRON_CoreLibrary.execute_console_command(cmd)

    ##########################
    # ------- Import functions
    def reimport_camera(self):
        """
        Re-imports new camera
        """
        # todo: need to update to use new methods and generic workflow
        # # get the world for this context
        # world = unreal.EditorLevelLibrary.get_editor_world()
        #
        # print(f'World is {world}')
        #
        # if world is None:
        #     unreal.log_error('World for GS{0:03d}_{1:03d}_{2:04d} is not loaded'.format(self.episode,
        #                                                                                 self.scene,
        #                                                                                 self.shot))
        #     return
        #
        # # check to make sure that our camera has a binding
        # if self.camera.binding is None:
        #     unreal.log_error('Could not find camera binding!')
        #     return
        #
        # # make sure that we have a valid fbx to import from
        # camera_fbx = self.camera.get_fbx()
        # if not camera_fbx:
        #     return
        #
        # unreal.SequencerTools.import_level_sequence_fbx(world,
        #                                                 self.asset,
        #                                                 [self.camera.binding],
        #                                                 self.camera.get_import_settings(),
        #                                                 camera_fbx)
        #
        # # follow up by setting scale
        # scale_factor = self.camera.get_scale_factor()
        # self.camera.set_scale(scale_factor, False)

    def set_characters(self):
        """
        Attempts to set up the shot with the correct actor bp's
        :return:
        """
        # todo: need to update to use new methods and generic workflow
        # print('Setting up characters')
        #
        # # get a list of assets for this shot
        # assets = self.sg_data['assets']
        #
        # dpt_tag = self._get_dpt_tag(unreal.DepartmentTag.ANIMATION)
        # if not dpt_tag:
        #     unreal.log_warning(f"Unable to find Animation department data")
        #     return
        #
        # # get the anim sequence for this sequence
        # anm_sequence = self.get_subscene(dpt_tag)
        #
        # if not anm_sequence:
        #     unreal.log_error(f"Unable to find anm sequence!")
        #     return
        #
        # # get bound objects to our anm sequence
        # world = unreal.EditorLevelLibrary().get_editor_world()
        # playback_range = anm_sequence['sequence'].get_playback_range()
        # spawnables = anm_sequence['sequence'].get_spawnables()
        #
        # bound_objects = unreal.SequencerTools().get_bound_objects(world, anm_sequence['sequence'], spawnables,
        #                                                           playback_range)
        #
        # # ## -------------------------------------------------------------------------------------- ## #
        # # ## Add Characters
        # # ## -------------------------------------------------------------------------------------- ## #
        #
        # # go through each object we should have, if it already is spawned all good
        # # if not then we want to add it
        # for i in self.sg_data['assets']:
        #
        #     # make sure we have the correct asset data
        #     asset_data = bron_shotgrid.get_entity(self.project,
        #                                           'Asset',
        #                                           sg_id=i['id'],
        #                                           additional_filters=[['sg_asset_type', 'is', 'Character']])
        #
        #     if not asset_data:
        #         continue
        #
        #     # todo: a bit of finangling to do here as the folder structure and naming of
        #     #       fields in shotgrid don't match. Should clean up with cleaning of folder structure
        #     asset_type = asset_data['sg_asset_type']
        #     if not asset_type == "Character":
        #         asset_type = "Props"
        #     else:
        #         asset_type = "Characters"
        #
        #     # todo: do we want to pull this data out into separate shotgrid fields?
        #     # clean up asset_name and get expected character bp path
        #     asset_name = asset_data['sg_asset_1']
        #     root_name = asset_name.rsplit("_", 1)[0]
        #     variation = asset_name.rsplit("_", 1)[-1]
        #
        #     char_bp_path = bron_paths.character_bp[self.project].format(ASSETTYPE=asset_type,
        #                                                                 PARENT=root_name,
        #                                                                 ASSET=asset_name)
        #
        #     if not unreal.EditorAssetLibrary().does_asset_exist(char_bp_path):
        #         unreal.log_warning(f"Unable to find blueprint for {asset_data['code']}")
        #         print(f'Char BP path: {char_bp_path}')
        #         continue
        #
        #     # get generated blueprint class
        #     bp_asset = unreal.EditorAssetLibrary.load_blueprint_class(char_bp_path)
        #
        #     chr_binding = None
        #     # go through our bound objects and see if we find a match
        #     # if we do then set the seq binding and remove the obj from the bound_objects list
        #     for obj in bound_objects:
        #         # todo: assumes that a binding proxy has only one bind
        #         # print(obj.bound_objects[0].get_editor_property('Animation'))
        #         bound_class = obj.bound_objects[0].get_class()
        #         if bound_class == bp_asset:
        #             print('Found a match!!!')
        #             chr_binding = obj.binding_proxy
        #             bound_objects.remove(obj)
        #
        #     print(f"Binding: {chr_binding}")
        #     # if we haven't found a match then we want to add
        #     if not chr_binding:
        #         print("could not find binding")
        #         chr_binding = anm_sequence['sequence'].add_spawnable_from_class(bp_asset)

        unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()

    def import_animations(self):
        """
        Will attempt to import the animations for this shot

        @return None
        """
        # todo: need to update to use new methods and generic workflow
        # print('Importing animations')
        # anim_folder = self._get_import_folder()
        #
        # if not os.path.exists(anim_folder):
        #     unreal.log_error('Could not find animation publish folder {}'.format(anim_folder))
        #     return
        #
        # # get all our assets that we currently have
        # asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
        # assets = get_assets_in_folder(self.animation_folder)
        #
        # existing_assets = {}
        #
        # for asset in assets:
        #     if asset.asset_class == 'AnimSequence':
        #         asset_str = unreal.StringLibrary.conv_name_to_string(asset.asset_name)
        #         existing_assets[asset_str] = asset
        #
        # for full_file_name in os.listdir(anim_folder):
        #     file_name = os.path.splitext(full_file_name)[0]
        #
        #     if file_name in existing_assets.keys():
        #         unreal.log('Found existing asset')
        #         animation_full_path = self.animation_folder + "/" + file_name
        #
        #         animation_sequence = unreal.load_asset(animation_full_path)
        #
        #         unreal.log("Reimporting Animation sequence: " + file_name)
        #         reimport_animation_sequence(animation_sequence,
        #                                     self.episode,
        #                                     self.scene)
        #     else:
        #         # unreal.log_error(file_name)
        #
        #         char = file_name.split('_')[5]
        #
        #         unreal.log("Looking up Skeleton for {}".format(char))
        #         print(file_name)
        #
        #         # attempt to get the skeleton from the skeleton dictionary
        #         skelly_table_path = "/Game/_Show_Tools/SceneSetup/Data/CharacterSkeletonDataTable"
        #         skelly_table = unreal.EditorAssetLibrary.load_asset(skelly_table_path)
        #
        #         skeleton_path = get_datatable_info(skelly_table, char, 'skeletonLocation')
        #
        #         # if we have a valid skeleton to import against then we can import the file
        #         if skeleton_path is not None:
        #             skeleton = unreal.EditorAssetLibrary.load_asset(skeleton_path)
        #             unreal.log("Importing Animation sequence: {}".format(file_name))
        #             full_import_path = os.path.join(anim_folder, full_file_name)
        #             import_animation_sequence(file_name,
        #                                       self.animation_folder,
        #                                       full_import_path,
        #                                       skeleton)
        #         else:
        #             unreal.log_warning('Unable to find appropriate skeleton for {}'.format(char))
        return

    def import_audio(self):
        """
        Imports audio files for this shot
        """
        # todo: need to update to use new methods and generic workflow
        # print('Importing audio')
        # self._update_perforce(dpt='audio')
        #
        # audio_folder = self._get_import_folder(dpt='audio')
        #
        # if not os.path.exists(audio_folder):
        #     unreal.log_error(f'Unable to locate audio folder: {audio_folder}')
        #     return
        #
        # # get all our assets that we currently have
        # asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
        # assets = get_assets_in_folder(self.audio_folder)
        #
        # existing_assets = {}
        #
        # # get all the currently existing assets
        # for asset in assets:
        #     if asset.asset_class == 'SoundWave':
        #         asset_str = unreal.StringLibrary.conv_name_to_string(asset.asset_name)
        #         existing_assets[asset_str] = asset
        #         print(asset_str)
        #
        # regex = re.compile("^GS\d{3}_\d{3}_\d{4}$")
        #
        # for full_file_name in os.listdir(audio_folder):
        #     file_name = os.path.splitext(full_file_name)[0]
        #
        #     if regex.search(file_name):
        #         clean_name = file_name.replace('GS', 'SW_')
        #         unreal.log(f"Importing Audio File: {clean_name}")
        #         file_path = os.path.join(audio_folder, full_file_name)
        #
        #         # clean path
        #         if "C:/shared/gos/shots" not in file_path:
        #             end_part = file_path.split("{}/{}".format(self.episode, self.scene))[-1]
        #             file_path = "C:\\shared\\gos\\shots\\{}\\{}\\{}".format(self.episode, self.scene, end_part)
        #
        #         # todo: check here if the unreal file is pulling from the same file
        #         print(f'Full path: {file_path}')
        #
        #         if not os.path.exists(file_path):
        #             unreal.log_error(f'Could not find file {file_path} on disk')
        #             return
        #
        #         import_task = _make_import_task(clean_name, self.audio_folder, file_path, None)
        #         _run_import_task(import_task)

    def get_subscene(self, dept_tag):
        """
        Checks the subscene associated with the Shot Sequence and returns the data for that subscene

        @param dept_tag: {str} Dept tag to get info for
        """
        # todo: leaving for legacy calls but should be replaced with self._get_subscene_track
        # # check if we have subscenes at all
        # if not self.subscenes:
        #     unreal.log_warning(f'Unable to find any subcenes for {self.name}')
        #     return None
        #
        # # check to see if the tag passed in is valid
        # if dept_tag not in self.subscenes.keys():
        #     unreal.log_warning(f'Unable to find key {dept_tag} in subscenes fo {self.name}')
        #     return None
        #
        # return self.subscenes[dept_tag]
        return None

    def get_level_visibility(self):
        """
        Gets the level visibility track and returns what is visible
        """
        settings = unreal.SceneSetupSettings.get_default_object()
        levelvisDpt = settings.get_editor_property("LevelVisDepartment")

        dpt_tag = self._get_dpt_tag(levelvisDpt)

        # get the lgt scene and make sure something valid returns
        track_suffix = ['Scn', 'Grp', 'Shot']
        vis_tracks = [f"{dpt_tag}_{i}" for i in track_suffix]

        visible_levels = []
        for track_name in vis_tracks:
            vis_track = self._get_subscene_track(track_name)

            if not vis_track:
                unreal.log(f'Failed to locate Vis track {track_name}')
                continue

            sections = self._get_subscene_sections(vis_track)

            if len(sections) == 0:
                unreal.log(f"Unable to find a section for the Vis track {track_name}")
                continue
            elif len(sections) > 1:
                unreal.log_error(f"Found more than one section of Vis track {track_name}")
                continue

            # get the lighting sequence and find the tracks
            sequence = sections[0]['sequence']

            tracks = [track for track in sequence.get_master_tracks()
                      if track.__class__ == unreal.MovieSceneLevelVisibilityTrack]
            print('#-----')
            # go through each track and find the level visibility section that is visible
            # add any visible levels to the list
            for track in tracks:
                print(track)
                for section in track.get_sections():
                    print(section.get_visibility())
                    if section.get_visibility() == 0:
                        print("working here")
                        visible_levels.extend(section.get_level_names())
                    if section.get_visibility() == 1:
                        print('Exclude these levels')

        print(visible_levels)

        return visible_levels

    def create_map(self):
        """
        Creates a new level for this shot to override renders and loads
        """
        # first check to see if we have a shot map override and if not attempt to create one
        if self.world == self.scene_level_path:
            unreal.log('We do not have a level override')
            success = unreal.EditorLevelLibrary().new_level(self.shot_level_path)

            # make sure that the level is created
            if success:
                self._world = None
            else:
                unreal.log_warning(f'Failed to create level {self.shot_level_path}')
                return
        # if the shot override exists then we just need to load it
        self.load(True)

    def update_map(self):
        """
        Will attempt to update the map with the correct levels based on level visiblity for this shot only
        """
        unreal.log('Updating map!!!')

        if not self.world == self.scene_level_path:
            world_asset = unreal.load_asset(self.world)

            # go through the current levels and get their names
            if world_asset == unreal.EditorLevelLibrary().get_editor_world():
                levels = unreal.EditorLevelUtils().get_levels(world_asset)
                print('Levels are....')
                for i in levels:
                    print(i)

                visible_levels = self.get_level_visibility()

                # first go through each level and if it is not in the visibility track
                # then we want to remove it
                for i in levels:
                    world = i.get_outer()
                    print(f"World is: {world}")

                    if not world == world_asset:
                        if not world.get_fname() in visible_levels:
                            # print(f'{world.get_name()} does not belong!')
                            streaming_level = unreal.GameplayStatics().get_streaming_level(world_asset,
                                                                                           world.get_name())

                            streaming_level.set_is_requesting_unload_and_removal(True)

                print(f"Visible levels: {visible_levels}")
                # # now go and make sure that all the right levels are loaded
                for level in visible_levels:
                    print(f"Level is: {level}")
                    if not unreal.GameplayStatics().get_streaming_level(world_asset, level):
                        streaming_level = unreal.GameplayStatics().get_streaming_level(
                            unreal.load_asset(self.scene_level_path),
                            level)

                        print(f"Streaming level: {streaming_level}")

                        if streaming_level:
                            streaming_world = streaming_level.get_editor_property('world_asset')
                            unreal.EditorLevelUtils().add_level_to_world(world_asset,
                                                                         streaming_world.get_path_name(),
                                                                         unreal.LevelStreamingDynamic)

                # save the level
                # todo: if a level is to removed the changes won't reflect immediately, level may need to be reloaded
                #       reloading will reset the scene setup tool so for now we won't reload until the user says so
                unreal.EditorLevelLibrary().save_current_level()

            else:
                unreal.log_warning(f'Shot {self.name} level is not loaded. Level needs to be loaded to update')

        else:
            unreal.log_warning(f'Shot {self.name} does not have a level override. Cannot update!')

    def set_prop_offset(self):
        """
        Sets the prop offset in the env sub sequence based on the json file written out from Maya

        Legacy function for old workflow. Keeping around but needs to be relooked at
        """

        offset_data = self.offset_data

        if not offset_data:
            unreal.log(f'No offset data found for {self.name}')
            return None

        all_actors = unreal.GameplayStatics.get_all_actors_of_class(unreal.EditorLevelLibrary.get_editor_world(),
                                                                    unreal.StaticMeshActor)

        actor_data = {}
        for actor in all_actors:
            actor_data[actor.get_actor_label()] = actor
            # print(actor.get_actor_label())

        env_track = self.subscenes['Env']
        env_sequence = env_track['sequence']

        # go through all the objects that we have offset data for
        for i in offset_data.keys():
            print('##-----------------##')
            print(i)

            if i not in actor_data.keys():
                unreal.log_warning(f'Could not find item {i}')
                continue

            print(actor_data[i])
            item_data = self.offset_data[i]
            print(item_data)
            # get a binding
            binding = env_sequence.find_binding_by_name(i)

            # check to see if binding is valid and if not we'll add it as a possessable
            if not binding.is_valid():
                print('Binding not valid!')
                if i in actor_data.keys():
                    binding = env_sequence.add_possessable(actor_data[i])

                    # if this failed, throw error and continue
                    if not binding.is_valid():
                        unreal.log_error(f'Failed to create binding for {i}')
                        continue

            print(binding)
            transform_tracks = binding.find_tracks_by_type(unreal.MovieScene3DTransformTrack)

            if not transform_tracks:
                print('could not find transform track')
                transform_track = binding.add_track(unreal.MovieScene3DTransformTrack)
            else:
                transform_track = transform_tracks[0]

            # print(transform_track)
            if not transform_track.get_sections():
                section = transform_track.add_section()

            else:
                section = transform_track.get_sections()[0]

            section.set_range(self.start, self.end)

            channels = section.get_channels()

            # todo: hacking in an offset for 107. Should have this tied into the UI
            #       somehow? Or set global position and have unreal figure out correct offset?
            offset = 0
            if self.scene == 107:
                offset = 62

            # set the offset values
            channels[0].set_default(item_data['transform']['x'])
            channels[1].set_default(item_data['transform']['y'])
            channels[2].set_default(item_data['transform']['z'] - offset)
            channels[3].set_default(item_data['rotation']['x'])
            channels[4].set_default(item_data['rotation']['y'])
            channels[5].set_default(item_data['rotation']['z'])

        unreal.LevelSequenceEditorBlueprintLibrary.refresh_current_level_sequence()


# todo: whole camera class needs to be updated to new methods. Keeping around as reference but can't call this
class BronCamera:
    seq_asset = None
    binding = None
    settings = None

    camera_class = None

    seq_tracks = {}
    # tracks = {'focallength': None,
    #           'scale': None,
    #           'filmback': {'SensorHeight': None,
    #                        'SensorWidth': None}}

    # properties
    _cam_component = None
    _scale = None
    _focal_length = None
    _filmback = None

    # base_filmback_settings = {'SensorWidth': 54.119999,
    #                           'SensorHeight': 30.40001}

    def __init__(self, seq_asset):
        """
        Initialize the camera class

        :seq_asset: (BronShotSequence) The shot sequence object this camera belongs to
        """
        self.seq_asset = seq_asset
        self.update()

        if not self.binding:
            unreal.log_warning('Instance does not have valid camera binding!')
            return None

    # --- Setup Functions --- #
    def update(self):
        """
        Creates a camera for the given shot sequence

        """
        # get camera class from project settings
        self.settings = unreal.SceneSetupSettings.get_default_object()
        camera_path = self.settings.get_editor_property('CameraPath')

        # set up info about the camera
        self.camera_class = unreal.EditorAssetLibrary.load_blueprint_class(camera_path)

        if not self.seq_asset:
            unreal.log_error(f"No shot sequence is set. Cannot create Camera")
            return None

        # todo: write in a check that if a cine camera exists that isn't of type of our camera then it
        #       should copy that camera data across
        binding = None
        for spawnable in self.seq_asset.asset.get_spawnables():
            obj_template = spawnable.get_object_template()

            # check to see if the spawnable is one we want
            if obj_template.get_class() == self.camera_class:
                if binding is not None:
                    unreal.log_error('Found more than one camera binding!')
                    return
                binding = spawnable

        self.binding = binding

        # if we didn't find a binding create a camera
        if not self.binding:
            unreal.log(f"Unable to find a camera, creating one!")
            self.binding = self.seq_asset.asset.add_spawnable_from_class(self.camera_class)
            self.binding.set_display_name(f"{self.seq_asset.name}_Cam")

        binding_proxy = self.binding.get_binding_id()

        # check to see if we have a cam component proxy and if not we need to add it
        if not self.camera_component:
            # get the object bound to the camera proxy
            world = unreal.EditorLevelLibrary().get_editor_world()
            playback_range = self.seq_asset.asset.get_playback_range()
            bound_objects = unreal.SequencerTools.get_bound_objects(world,
                                                                    self.seq_asset.asset,
                                                                    [self.binding],
                                                                    playback_range)

            # todo: currently assumes that there is only one thing bound to the camera. Should be safe but...
            # get the camera component and add it as a possessable
            camComp = bound_objects[0].bound_objects[0].get_editor_property("CameraComponent")
            self._cam_component = unreal.MovieSceneSequenceExtensions.add_possessable(self.seq_asset.asset,
                                                                                      camComp)

        print('###Camera tracks-------------###')
        # setting up the scale attribute
        # cam_tracks = {}
        for i in self.binding.find_tracks_by_type(unreal.MovieSceneDoubleTrack):
            self.seq_tracks[str(i.get_property_name())] = i

        if 'scale' not in self.seq_tracks.keys():
            new_track = self.binding.add_track(track_type=unreal.MovieSceneDoubleTrack)
            new_track.set_property_name_and_path('scale', 'scale')

            self.seq_tracks['scale'] = new_track

        print(self.seq_tracks.keys())
        track = self.seq_tracks['scale']
        print(f"Track is: {track}")
        self.update_section(track)

        print('###Camera Component tracks-------------###')
        # now setup tracks or get handles to them if they exist
        for i in self.camera_component.get_tracks():
            self.seq_tracks[str(i.get_property_name())] = i

        tracks = {"CurrentFocalLength": "CurrentFocalLength",
                  "ManualFocusDistance": "FocusSettings.ManualFocusDistance",
                  "CurrentAperture": "CurrentAperture",
                  "SensorHeight": "Filmback.SensorHeight",
                  "SensorWidth": "Filmback.SensorWidth"}

        filmback = self.settings.get_editor_property('Filmback')

        for track_name in tracks.keys():
            if track_name not in self.seq_tracks.keys():
                new_track = self.camera_component.add_track(track_type=unreal.MovieSceneFloatTrack)
                new_track.set_property_name_and_path(track_name, tracks[track_name])

                self.seq_tracks[track_name] = new_track

            track = self.seq_tracks[track_name]
            self.update_section(track)

        # todo: assumes that each track only has one section and no keys, will fail if this isn't the case
        self.seq_tracks['SensorHeight'].get_sections()[0].get_channels()[0].set_default(filmback.y*self.scale)
        self.seq_tracks['SensorWidth'].get_sections()[0].get_channels()[0].set_default(filmback.x*self.scale)

        print(f"Scale is set to {self.scale}")

        print('###-------------------###\n\n\n')

    # ------- Properties
    @property
    def camera_component(self):
        """
        Gets the camera component
        """
        if not self._cam_component:
            for i in self.binding.get_child_possessables():
                if "CineCameraComponent" == i.get_possessed_object_class().get_name():
                    self._cam_component = i

        return self._cam_component

    @property
    def scale(self):
        """
        Get the camera scale
        """
        # if we have the scale already set, return that
        if 'scale' not in self.seq_tracks:
            unreal.log_warning(f"Scale is not set for {self.binding.get_display_name()}")
            return 1

        track = self.seq_tracks['scale']

        section = self.get_section(track)
        channel = section.get_channels()[0]

        if not channel.has_default():
            # todo: assumes that default value of scale is 1, ideally would check class defaults
            return 1
        else:
            return channel.get_default()

    @scale.setter
    def scale(self, scale):
        """
        Setting the scale factor
        """
        # todo: currently if we can't find the scale track we bail. If setting scale maybe we should add track if it
        #       doesn't already exist
        if 'scale' not in self.seq_tracks:
            unreal.log_warning(f"Unable to find scale track. Update and try again!")
            return

        # todo: currently doesn't deal with key framed cameras but sets default values instead
        scale_factor = scale / self.scale
        print(f'Update scale to: {scale_factor}')
        section = self.get_section(self.seq_tracks['scale'])
        channel = section.get_channels()[0]

        channel.set_default(scale)

        # set the filmback (we can do this using the plugin settings to reset this each time)
        filmback = self.settings.get_editor_property('Filmback')
        self.seq_tracks['SensorHeight'].get_sections()[0].get_channels()[0].set_default(filmback.y * self.scale)
        self.seq_tracks['SensorWidth'].get_sections()[0].get_channels()[0].set_default(filmback.x * self.scale)

        # todo: this assumes everything lines up before hand. Do we want something that allows users to set focal length
        #       somewhere else and then drive the actual focal length
        # now set the focal length, this is done by taking current value and multiplying by scale factor
        focal_length_channel = self.seq_tracks['CurrentFocalLength'].get_sections()[0].get_channels()[0]
        curr_focal_length = focal_length_channel.get_default()
        if curr_focal_length == 0:
            curr_focal_length = 35.0

        focal_length_channel.set_default(curr_focal_length*scale_factor)

        # now we have set default we need to check if there are any key frames, if there are we need to set
        # all of them as well
        print(focal_length_channel.get_num_keys())
        if focal_length_channel.get_num_keys() > 0:
            keys = focal_length_channel.get_keys()
            for key in keys:
                print(key)
                value = key.get_value()
                key.set_value(value*scale_factor)

#         # if not we'll need to go find it
#         else:
#             seq_tracks = {}
#
#             # find all our tracks
#             for i in self.binding.get_tracks():
#                 if type(i) == unreal.MovieSceneFloatTrack:
#                     name = str(i.get_property_name())
#                     seq_tracks[name] = i
#
#             # if we found it then set and return
#             if 'scale' in seq_tracks:
#                 self._scale = seq_tracks['scale']
#                 return self._scale
#
#             else:
#                 unreal.log('Looks like we do not have scale in sequencer o.O')
#
#                 # add a new track for the camera component and point it to the film back setting
#                 track = self.binding.add_track(track_type=unreal.MovieSceneFloatTrack)
#                 track.set_property_name_and_path('scale', 'scale')
#
#                 # add a section and get the channel
#                 section = track.add_section()
#                 section.set_range(0, 100000)
#
#                 # lock the section so we can't touch it
#                 section.set_editor_property('is_locked', True)
#                 self._scale = track
#
#                 return self._scale
#
#     @property
#     def focal_length(self):
#         """
#         Gets the focal length track for the camera
#         """
#         if self._focal_length:
#             return self._focal_length
#
#         component_tracks = {}
#
#         # need to make sure we have a component available on the sequence
#         if self.component_binding:
#             # get all the track on the cam component
#             for i in self.component_binding.get_tracks():
#                 if type(i) == unreal.MovieSceneFloatTrack:
#                     name = str(i.get_property_name())
#                     component_tracks[name] = i
#
#             if 'CurrentFocalLength' in component_tracks:
#                 self._focal_length = component_tracks['CurrentFocalLength']
#                 return self._focal_length
#
#         else:
#             self._focal_length = None
#             return self._focal_length
#
#     @property
#     def filmback(self):
#         """
#         Gets the filmback for the camera
#         """
#         if self._filmback:
#             return self._filmback
#
#         if self.component_binding:
#
#             component_tracks = {}
#
#             # get all the track on the cam component
#             for i in self.component_binding.get_tracks():
#                 if type(i) == unreal.MovieSceneFloatTrack:
#                     name = str(i.get_property_name())
#                     component_tracks[name] = i
#
#             params = ['SensorWidth', 'SensorHeight']
#             self._filmback = {}
#
#             # go through our filmback settings and hold the track information
#             # or create the track if it doesn't exist
#             for param in params:
#                 if param in component_tracks:
#                     self._filmback[param] = component_tracks[param]
#
#                 # if we can't find the filmback tracks we need to set them up
#                 else:
#                     unreal.log_warning('Looks like we dont have {} in sequencer o.O'.format(param))
#                     # add a new track for the camera component and point it to the film back setting
#                     track = self.component_binding.add_track(track_type=unreal.MovieSceneFloatTrack)
#                     track.set_property_name_and_path(param, 'Filmback.{}'.format(param))
#
#                     # add a section to valid the track
#                     section = track.add_section()
#                     section.set_range(0, 100000)
#
#                     # lock the section so we can't touch it
#                     section.set_editor_property('is_locked', True)
#                     self._filmback[param] = track
#             return self._filmback
#
#         else:
#             self._filmback = None

    # --- Helper Functions --- #
    @staticmethod
    def get_section(track):
        """
        Checks the track for a section and if one doesn't exist will create the section
        """
        # first make sure that our track passed in is valid
        if not isinstance(track, unreal.MovieScenePropertyTrack):
            unreal.log_warning(f'Cannot update section. Invalid track passed in')
            return

        # make sure that the section exists, if not create new section
        sections = track.get_sections()
        if not sections:
            section = track.add_section()
        else:
            # todo: here we are just taking the first section, probably want to check this...
            section = sections[0]

        return section

    def update_section(self, track):
        """
        Given a track will update or create a section to make sure the range matches with the shot
        """
        # first make sure that our track passed in is valid
        if not isinstance(track, unreal.MovieScenePropertyTrack):
            unreal.log_warning(f'Cannot update section. Invalid track passed in')
            return

        # make sure that the section exists, if not create new section
        section = self.get_section(track)

        section.set_range(self.seq_asset.start - self.seq_asset.sg_data['sg_preroll'],
                          self.seq_asset.end)

        section.set_editor_property('is_locked', True)

#     def get_fbx(self):
#         """
#         Attempts to find the on disk fbx for this camera
#         """
#
#         if not self.seq_asset:
#             unreal.log_error('Camera does not have a sequence context')
#             return
#
#         camera_name = "A_{0:03d}_{1:03d}_{2:04d}_camera_01.fbx".format(self.seq_asset.episode,
#                                                                        self.seq_asset.scene,
#                                                                        self.seq_asset.shot)
#
#         camera_fbx = "C:/shared/gos/shots/{0:03d}/{1:03d}/{2:04d}/publish/animation/{3}".format(self.seq_asset.episode,
#                                                                                               self.seq_asset.scene,
#                                                                                               self.seq_asset.shot,
#                                                                                               camera_name)
#
#         if not os.path.exists(camera_fbx):
#             unreal.log_error('Could not find camera file: {}'.format(camera_fbx))
#             return None
#
#         print('Found camera!!!')
#         return camera_fbx
#
#     @staticmethod
#     def get_import_settings():
#         """
#         Returns import settings to import that camera animation data
#         """
#         import_options = unreal.MovieSceneUserImportFBXSettings()
#         import_options.set_editor_property("convert_scene_unit", True)
#         import_options.set_editor_property("create_cameras", False)
#         import_options.set_editor_property("force_front_x_axis", False)
#         import_options.set_editor_property("match_by_name_only", False)
#         import_options.set_editor_property("reduce_keys", False)
#         import_options.set_editor_property("replace_transform_track", True)
#
#         return import_options
#
#     def get_scale_factor(self):
#         if self.binding is None:
#             unreal.log_warning('Camera does not have a binding!')
#             return
#
#         # get scale section
#         section = self.scale.get_sections()[0]
#         section.set_editor_property('is_locked', False)
#
#         # get the channel and any keys associated with it
#         channel = section.get_channels()[0]
#
#         preexisting_scale = channel.get_default()
#
#         if preexisting_scale == 0:
#             preexisting_scale = 1
#
#         return preexisting_scale
#
#     def set_scale(self, scale_factor, use_preexisting_scale=True):
#         """
#         Sets the scale of the camera
#         """
#         if self.binding is None:
#             unreal.log_warning('Camera does not have a binding!')
#             return
#
#         # get scale section
#         section = self.scale.get_sections()[0]
#         section.set_editor_property('is_locked', False)
#
#         # get the channel and any keys associated with it
#         channel = section.get_channels()[0]
#
#         preexisting_scale = channel.get_default()
#
#         if preexisting_scale == 0:
#             preexisting_scale = 1
#
#         print('Preexisting scale: {}'.format(preexisting_scale))
#
#         channel.set_default(scale_factor)
#         section.set_editor_property('is_locked', True)
#
#         # set the film back settings
#         for param in self.filmback.keys():
#             track = self.filmback[param]
#             section = track.get_sections()[0]
#
#             section.set_editor_property('is_locked', False)
#
#             # get the channel and any keys associated with it
#             channel = section.get_channels()[0]
#             num_keys = channel.get_num_keys()
#
#             # todo: we aren't dealing with keyframes yet but need to figure out how to resolve that
#             if num_keys != 0:
#                 unreal.log_warning('{} has keys. Not dealing with this now'.format(param))
#             # set the film back size and lock the section
#             else:
#                 channel.set_default(self.base_filmback_settings[param] * scale_factor)
#                 section.set_editor_property('is_locked', True)
#
#         # set the focal length
#         track = self.focal_length
#         section = track.get_sections()[0]
#
#         section.set_editor_property('is_locked', False)
#
#         # get the channel and any keys associated with it
#         channel = section.get_channels()[0]
#         num_keys = channel.get_num_keys()
#
#         # set the inital value in case there are no keys
#         initial_value = channel.get_default()
#
#         # if not use_preexisting_scale:
#         #    scale_factor = scale_factor/preexisting_scale
#         #    initial_value = initial_value/preexisting_scale
#
#         print('Scale factor: {}'.format(scale_factor))
#         print('Initial: {}'.format(initial_value))
#
#         channel.set_default(initial_value * scale_factor)
#
#         # if we have keys then we need to go and edit all of them
#         if num_keys != 0:
#             keys = channel.get_keys()
#
#             for key in keys:
#                 initial_value = key.get_value()
#
#                 if use_preexisting_scale:
#                     initial_value = initial_value / preexisting_scale
#
#                 key.set_value(initial_value * scale_factor)
#
#         section.set_editor_property('is_locked', True)


def cast(source, target):
    """
    Attempts to see if the target is the same as the source class
    """
    try:
        source.cast(target)
        return True
    except Exception as e:
        return False
