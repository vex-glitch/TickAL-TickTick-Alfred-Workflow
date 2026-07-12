"""Alfred Script Filter JSON helpers."""
import json
import sys


def item(uid="", title="", subtitle="", arg="", valid=True,
         icon_path=None, autocomplete=None, mods=None,
         variables=None, match=None, type_=None):
    result = {
        "title": title,
        "subtitle": subtitle,
        "arg": arg,
        "valid": valid,
    }
    if uid:
        result["uid"] = uid
    if icon_path:
        result["icon"] = {"path": icon_path}
    if autocomplete is not None:
        result["autocomplete"] = autocomplete
    if mods:
        result["mods"] = mods
    if variables:
        result["variables"] = variables
    if match:
        result["match"] = match
    if type_:
        result["type"] = type_
    return result


def output(items, variables=None, rerun=None, skipknowledge=False):
    result = {"items": items}
    if variables:
        result["variables"] = variables
    if rerun:
        result["rerun"] = rerun
    if skipknowledge:
        result["skipknowledge"] = True
    return json.dumps(result)


def error(message):
    return output([item(
        uid="error",
        title="Error",
        subtitle=message,
        valid=False,
    )])


def print_output(items, variables=None, rerun=None):
    print(output(items, variables=variables, rerun=rerun))


def print_error(message):
    print(error(message))
    sys.exit(0)
