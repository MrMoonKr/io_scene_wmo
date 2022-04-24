import bpy

# TODO: This is a temporary solution
# to easily make rotation/location-only models work by just dropping scale tracks.
# We should handle this when exporting, but i'm just leaving this here so testers can use it more easily.
def remove_scale_tracks():
    for action in bpy.data.actions:
        deletes = []
        for fcurve in action.fcurves:
            if not fcurve.data_path.startswith("pose.bones"):
                continue
            if not fcurve.data_path.endswith("scale"):
                continue
            deletes.append(fcurve)

        for delete in deletes:
            print(f"Deleting fcurve {delete.data_path}[{delete.array_index}]")
            action.fcurves.remove(delete)