from ..config import ADDON_MODULE_NAME

from typing import Optional
import bpy


def get_addon_preferences() -> 'WBS_AP_Preferences':
    """
    Gets current Blender addon preferences for this addon in any context.
    :return: Addon preferences.
    """
    return bpy.context.preferences.addons[ADDON_MODULE_NAME].preferences


def get_project_preferences() -> Optional['WBS_PG_ProjectPreferences']:
    """
    Gets current project preferences in any context.
    :return: Project preferences or None.
    """
    addon_preferences = get_addon_preferences()

    if not len(addon_preferences.projects):
        raise UserWarning("No active project. Check WBS settings.")

    return addon_preferences.projects[addon_preferences.active_project_index]


class WBS_UL_Projects(bpy.types.UIList):
    """ UI List displaying currently saved projects. """

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        split = layout.split(factor=0.3)
        split.prop(item, "name", text="", emboss=False, translate=False
                   , icon='RADIOBUT_ON' if index == data.active_project_index else 'RADIOBUT_OFF')

    def invoke(self, context, event):
        ...


class WBS_PG_ProjectPreferences(bpy.types.PropertyGroup):
    """ Property group holding data for project preferences set. """

    wow_path: bpy.props.StringProperty(
        name="WoW Client Path",
        subtype='DIR_PATH'
    )

    wmv_path: bpy.props.StringProperty(
        name="WoW Model Viewer Log Path",
        subtype='FILE_PATH'
    )

    wow_export_path: bpy.props.StringProperty(
        name="WoW Export Runtimelog Path",
        subtype='FILE_PATH'
    )

    noggit_red_path: bpy.props.StringProperty(
        name="Noggit Red log Path",
        subtype='FILE_PATH'
    )

    import_method: bpy.props.EnumProperty(
        name="Import Method",
        items=[
            ('WMV', "WMV", "Use WoW Model Viewer"),
            ('WowExport', "WowExport", "Use WoW Export"),
            ('NoggitRed', "NoggitRed", "Use Noggit Red"),
        ],
        default='WMV',
        description="Choose the preferred method of import for WoW files."
    )

    cache_dir_path: bpy.props.StringProperty(
        name="Cache Directory Path",
        description="Any folder that can be used to store textures and other temporary files.",
        subtype="DIR_PATH"
    )

    project_dir_path: bpy.props.StringProperty(
        name="Project Directory Path",
        description="A directory Blender saves WoW files to and treats it as top-priority patch.",
        subtype="DIR_PATH"
    )


class WBS_OT_ProjectListActions(bpy.types.Operator):
    """
    Moves items up and down the list of projects, adds or removes.
    """

    bl_idname = "wbs.project_list_action"
    bl_label = "List Actions"
    bl_description = "Move items up and down, add and remove"
    bl_options = {'REGISTER', 'INTERNAL'}

    action: bpy.props.EnumProperty(
        items=(
            ('UP', "Up", ""),
            ('DOWN', "Down", ""),
            ('REMOVE', "Remove", ""),
            ('ADD', "Add", "")))

    @classmethod
    def description(cls, context, properties):
        match properties.action:
            case 'UP':
                return "Move project up the list"
            case 'DOWN':
                return "Move project down the list"
            case 'ADD':
                return "Add new project"
            case 'REMOVE':
                return "Remove project from the list"
            case _:
                raise NotImplementedError()

    def invoke(self, context, event):
        addon_prefs = get_addon_preferences()
        idx = addon_prefs.active_project_index

        match self.action:
            case 'DOWN':
                if idx < len(addon_prefs.projects) - 1:
                    addon_prefs.projects.move(idx, idx + 1)
                    addon_prefs.active_project_index += 1
            case 'UP':
                if idx >= 1:
                    addon_prefs.projects.move(idx, idx - 1)
                    addon_prefs.active_project_index -= 1
            case 'REMOVE':
                if len(addon_prefs.projects):
                    addon_prefs.active_project_index -= 1
                    addon_prefs.projects.remove(idx)
            case 'ADD':
                item = addon_prefs.projects.add()
                item.name = 'New project'
                addon_prefs.active_project_index = len(addon_prefs.projects) - 1

        return {"FINISHED"}


class WBS_AP_Preferences(bpy.types.AddonPreferences):
    """
    Stores global preferences for the addon.
    """

    bl_idname = 'io_scene_wmo'

    projects: bpy.props.CollectionProperty(
        type=WBS_PG_ProjectPreferences,
        name='Projects',
        description='Project presets.',
        options=set()
    )

    active_project_index: bpy.props.IntProperty(default=0)

    def draw(self, context: bpy.types.Context):
        layout = self.layout

        row = layout.row()
        row.template_list('WBS_UL_Projects', '', self, 'projects', self, 'active_project_index', rows=2)

        col = row.column(align=True)
        col.operator("wbs.project_list_action", icon='ADD', text="").action = 'ADD'
        col.operator("wbs.project_list_action", icon='REMOVE', text="").action = 'REMOVE'
        col.separator()
        col.operator("wbs.project_list_action", icon='TRIA_UP', text="").action = 'UP'
        col.operator("wbs.project_list_action", icon='TRIA_DOWN', text="").action = 'DOWN'
        col.separator()

        if proj_prefs := get_project_preferences():
            col = layout.column(align=True)
            col.label(text='Project settings:', icon='SETTINGS')
            box = col.box()
            box.prop(proj_prefs, 'wow_path')
            box.prop(proj_prefs, 'import_method')
            if proj_prefs.import_method == 'WMV':
                box.prop(proj_prefs, 'wmv_path')
            elif proj_prefs.import_method == 'WowExport':
                box.prop(proj_prefs, 'wow_export_path')  
            elif proj_prefs.import_method == 'NoggitRed':
                box.prop(proj_prefs, 'noggit_red_path')                 
            box.prop(proj_prefs, 'cache_dir_path')
            box.prop(proj_prefs, 'project_dir_path')
