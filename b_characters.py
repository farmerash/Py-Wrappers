from importlib import *
import unreal
import os
from subprocess import Popen, PIPE
from p4_api import p4_handler

from . import bron_shotgrid, bron_paths
reload(bron_shotgrid)
reload(bron_paths)

# ##-------------------------------------------------------------------------------------- ## #
# ##--- Helper functions ----------------------------------------------------------------- ## #


def get_parent_char(prj, sg_char_info):
    """
    Given character info will return data for parent character
    :param sg_char_info: (dict) Sg data for character
    :return: (dict) sg_data for parent
    """

    # if we don't have a parent set up return itself
    # else return the details of the parent asset
    if not sg_char_info['sg_parent']:
        return sg_char_info
    else:
        return bron_shotgrid.get_entity(prj, 'Asset', sg_id=sg_char_info['sg_parent']['id'])


def _update_perforce_folder(path, p4v_user, workspace):
    """
    Updates a perforce folder given a path and user
    :param path: (str) Path user wants to update
    :param p4v_user: (str) user name to use in perforce command
    :return: (bool) True or false depending on success
    """
    print(f'Updating perforce: {path}')

    if not os.path.exists(path):
        unreal.log_error(f'Cannot update folder. Does not exist on disk. {path}')
        return False

    handler = p4_handler.P4Handler(p4v_user)
    handler.set_client_name(workspace)

    # attempt to update
    try:
        handler.sync(file_path=f"{path}\\...")
        print('File is synced!')
    except Exception as e:
        print(f'Failed: {e}')


def _resolve_links(path):
    """
    Resolves symlinks and junctions to their actual paths
    :param path:
    :return:
    """
    # see if we can resolve the path to its actual location so we can update perforce
    with Popen(f"fsutil reparsepoint query \"{path}\"", stdout=PIPE, bufsize=1,
               universal_newlines=True) as p:
        for line in p.stdout:
            if 'Print Name:' in line:
                resolved_folder = line.split('Print Name:')[-1].lstrip(' ').rstrip('\n')

    return resolved_folder


def _get_rig_root(prj, sg_chr_info, resolve=False):
    """
    Gets the root folder for rigs, Resolves paths if requested
    :param prj: (str) project code
    :param sg_chr_info: (dict) sg data for the asset
    :param resolve: (bool) if True will attempt to resolve the file path before passing it back
    :return: (str) path to rig root folder
    """
    asset_type = sg_chr_info['sg_asset_type']
    rig_root = bron_paths.offline_rig_root[prj][asset_type].format(CHR=sg_chr_info['sg_asset_1'])

    if not os.path.exists(rig_root):
        unreal.log_error(f'Unable to find rig root: {rig_root}')
        return

    if resolve:
        return _resolve_links(rig_root)
    else:
        return rig_root


def _get_rig_folder(prj, sg_char_info, resolve=False):
    """
    Gets the folder where we expect to see the rigs
    :param prj: (str) project code
    :param sg_char_info: (dict) sg data for the asset
    :return: (str) path to rig folder
    """
    asset_type = sg_char_info['sg_asset_type']
    asset_name = sg_char_info['sg_asset_1']

    rig_root = _get_rig_root(prj, sg_char_info, resolve=resolve)
    if not rig_root:
        return None

    character_rig_folder = bron_paths.offline_rig_folder[prj][asset_type].format(CHR=asset_name)

    rig_folder = os.path.join(rig_root, character_rig_folder)

    if not os.path.exists(rig_folder):
        unreal.log_error(f'Unable to find rig folder: {rig_folder}')
        return None

    return rig_folder


def _skmesh_import_options(sg_chr_info, create_skel, skel):
    """
    Sets up import data for SKMesh files
    :param sg_chr_info: (dict) sg_data for character
    :param skel: (str) path to skeleton object
    :return: Sk mesh import options
    """
    options = unreal.FbxImportUI()

    options.import_mesh = True
    options.import_textures = False
    options.import_materials = False
    options.import_as_skeletal = True
    options.import_animations = False

    options.create_physics_asset = True

    # todo: what to do if skeleton doesn't exist
    # if we want to create a skel skip this section and one will be generated
    if not create_skel:
        # if no skeleton provided then we need to go to the data and look for one
        # else use the one provided
        if not skel:
            if not unreal.EditorAssetLibrary.does_asset_exist(sg_chr_info['sg_ue_skeletonpath']):
                unreal.log_warning(f"Unable to find skeleton {sg_chr_info['sg_ue_skeletonpath']}")
                return None

            options.skeleton = unreal.load_asset(sg_chr_info['sg_ue_skeletonpath'])
        else:
            options.skeleton = unreal.load_asset(skel)

    # setup sk_mesh options
    sk_options = unreal.FbxSkeletalMeshImportData()

    # misc settings
    sk_options.convert_scene_unit = False
    sk_options.convert_scene  = True

    # mesh settings
    sk_options.set_editor_property("update_skeleton_reference_pose", False)
    sk_options.set_editor_property("use_t0_as_ref_pose", True)
    sk_options.set_editor_property("preserve_smoothing_groups", True)
    sk_options.set_editor_property("import_meshes_in_bone_hierarchy", False)
    sk_options.set_editor_property("import_morph_targets", True)
    sk_options.normal_import_method = unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS_AND_TANGENTS

    options.skeletal_mesh_import_data = sk_options

    return options


def _import_task(destination, filename, options):
    """
    Creates import task from inputs
    :type destination: (str) Folder we want to import to
    :type filename: (str) Path to file that we want to import
    :param options: (options) Import options object to define how to import object
    :return: (task) Task object ready for execution
    """

    task = unreal.AssetImportTask()

    task.set_editor_property("automated", True)
    task.set_editor_property("destination_path", destination)
    task.set_editor_property("factory", unreal.FbxFactory())
    task.set_editor_property("filename", filename)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("save", True)
    task.set_editor_property("options", options)

    return task


def _find_skeleton(folder):
    """
    Finds a skeleton in the folder
    :param folder: (str) folder path to look for skeleton in
    :return: (str) path to skeleton file
    """
    all_assets = unreal.EditorAssetLibrary().list_assets(folder, True, False)

    skeleton = None

    for i in all_assets:
        asset = unreal.EditorAssetLibrary().load_asset(i)

        if cast(asset, unreal.Skeleton):
            if skeleton:
                unreal.log_warning(f"Found multiple skeletons in {folder}. Can not deal with this o.O")
                return
            skeleton = i

    return skeleton


def cast(object_to_cast, object_class):
    try:
        return object_class.cast(object_to_cast)

    except Exception as e:
        return None


# ##-------------------------------------------------------------------------------------- ## #
# ##--- Callable functions --------------------------------------------------------------- ## #


def sync_rig_offline(prj, char):
    """
    Takes a character tag and locates it on disk and updates perforce folder

    :param prj: (str) project code
    :param char: (str) Shotgrid tag for character to update
    :return: None
    """

    # get asset info and make sure that we get something in return
    sg_chr_info = bron_shotgrid.get_entity(prj, 'Asset', additional_filters=[['sg_asset_1', 'is', char]])

    if not sg_chr_info:
        unreal.log_warning(f'Unable to find {char} in shotgrid')
        return

    # get the rig root folder and make sure that it exists on disk
    root_folder = _resolve_links(_get_rig_root(prj, sg_chr_info))
    if not root_folder:
        return

    workspace = root_folder.replace('/', '\\').rpartition('\\')[-1]

    rig_folder = bron_paths.offline_rig_folder['GS'][sg_chr_info['sg_asset_type']].format(CHR=sg_chr_info['sg_asset_1'])
    p4v_folder = os.path.join(root_folder, rig_folder)

    if not os.path.exists(p4v_folder):
        unreal.log_warning(f'Failed to find folder: {p4v_folder}')
        os.makedirs(p4v_folder)
        # return

    # update perforce folder
    _update_perforce_folder(p4v_folder, 'dave.alve', workspace)


def import_character(prj, char, create_skel=False):
    """
    Attempts to import character skeletal meshes into Unreal

    :param prj: (str) Code for the project we are working on
    :param char: (str) Shotgrid tag for the character to update/ingest
    :param create_skel: (bool) Whether or not we should create a skeleton if one doesn't exist
    :return: None
    """
    sync_rig_offline(prj, char)

    # get sg data for our character
    sg_chr_info = bron_shotgrid.get_entity(prj, 'Asset', additional_filters=[['sg_asset_1', 'is', char]])

    # make sure we get something back
    if not sg_chr_info:
        unreal.log_warning(f'Unable to find {char} in shotgrid')
        return

    # get the parent character
    parent_char = get_parent_char(prj, sg_chr_info)
    print(parent_char)

    # run some checks
    if parent_char['sg_ue_skeletonpath'] is None and create_skel is False:
        unreal.log_warning(f"{char} has parent {parent_char['code']} but no skeletal path is defined")
        return

    # get the rig folder and all the fbx files in there ready for import
    rig_folder = _get_rig_folder(prj, sg_chr_info)
    sk_meshes = [i for i in os.listdir(rig_folder) if i[-3:] == 'fbx']

    destination = bron_paths.rig_folder[prj][parent_char['sg_asset_type']].format(CHR=parent_char['sg_asset_1'])

    use_skel = None

    for i in sk_meshes:

        # lets skip over any hair mesh
        if '_hair' in i:
            unreal.log(f'Not importing hair mesh {i}')
            continue

        import_options = _skmesh_import_options(parent_char, create_skel, use_skel)

        mesh_path = os.path.join(rig_folder, i)
        task = _import_task(destination, mesh_path, import_options)

        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

        if create_skel:
            if not parent_char['sg_ue_skeletonpath']:
                skeleton = _find_skeleton(destination)
                use_skel = skeleton

        create_skel = False








