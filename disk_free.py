#!/usr/bin/python

# Copyright: (c) 2019, Thomas Elrod <thomas.elrod@va.gov>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

ANSIBLE_METADATA = {
    'metadata_version': '1.1',
    'status': ['preview'],
    'supported_by': 'community'
}

DOCUMENTATION = '''
---
module: disk_free

short_description: Check filesystem disk usage

version_added: "2.*"

description:
    - "Retrieve usage, in MiB, of a specified filesystem"
    - "Able to base return status on minimum free space provided"
    - "Optionally remove files to meet the minimum free space desired"

options:
    path:
        description:
            - Full path to filesystem to get the free space of.
        required: true
    unit:
        description:
            - The unit to use for size.
            - This applies to sizes provided in the options and those returned.
        required: false
        choices: [ byte, kB, KiB, MB, MiB, GB, GiB, TB, TiB, PB, PiB, EB, EiB ]
        default: MiB
    free:
        description:
            - The minimum free space required for a successful return.
        required: false
        default: 0
    ifree:
        description:
            - The minimum number of inodes required to be available for a successful return.
        required: false
        default: 0
    delete:
        description:
            - Optional files to remove to meet minimum free space requirements.
        required: false

author:
    - Thomas Elrod (@tomelrod)
'''

EXAMPLES = '''
# Get filesystem space usage data
- name: Get filesystem usage of /home
  disk_free:
    path: /home

# Test if a filesystem has a specified amount of free space
- name: Check /var/log filesystem free space
  disk_free:
    path: /var/log
    free: 2
    unit: GiB

# Test if a filesystem has a specified amount of free space
# If it's not remove some files/directories and check agian
- name: 
  disk_free:
    path: /opt
    free: 200
    delete:
      - /opt/run.log
      - /opt/backup.[3-5]*
'''

RETURN = '''
stat:
    description: dictionary containing the filesystem space usage data
    type: complex
    contains:
        size:
            description: size of given filesystem
            type: int
            sample: 189
        free:
            description: free space of given filesystem
            type: int
            sample: 74
        usage:
            description: percent of space used in given filesystem
            type: int
            sample: 61
        inode_count:
            description: number of inodes in given filesystem
            type: int
            sample: 51200
        inode_free:
            description: number of free inodes in given filesystem
            type: int
            sample: 51146
        inode_usage:
            description: percent of inodes used in given filesystem
            type: int
            sample: 1
'''

import os
import glob
import math
import shutil

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils._text import to_bytes


unit_map=dict(
    byte=1,
    kB=1000,
    KiB=1024,
    MB=1000**2,
    MiB=1024**2,
    GB=1000**3,
    GiB=1024**3,
    TB=1000**4,
    TiB=1024**4,
    PB=1000**5,
    PiB=1024**5,
    EB=1000**6,
    EiB=1024**6
)


def get_free(path):
    size=os.statvfs(path)
    fs_size = (size.f_blocks * size.f_frsize)
    fs_free = (size.f_bavail * size.f_frsize)
    fs_inodes = size.f_files
    fs_ifree = size.f_favail
    return dict( size=fs_size, free=fs_free, inodes=fs_inodes, ifree=fs_ifree )


def run_check(fstat, unit, want_free, want_ifree):
    if int(fstat['free']/unit) < want_free: return False
    if fstat['ifree'] < want_ifree: return False
    return True


def remove_files(path, delete):
    removal=False
    pDev = os.stat(path).st_dev
    # create list of paths to remove
    rm_list = []
    for p in delete:
        bp = to_bytes(p, errors='surrogate_or_strict')
        found = glob.glob(bp)
        for i in found:
            if os.stat(i).st_dev == pDev:
                rm_list.append(i)
    # go through the list removing the paths
    for p in rm_list:
        if os.path.isfile(p):
            os.remove(p)
            removal=True
        elif os.path.isdir(p):
            shutil.rmtree(p)
            removal=True
    return removal


def build_result(changed, fstat, unit):
    return dict(
        changed=changed,
        stat=dict(
            free=int(fstat['free']/unit),
            size=int(fstat['size']/unit),
            usage=100-int(math.floor( fstat['free']/fstat['size']*100 )),
            inode_free=fstat['ifree'],
            inode_count=fstat['inodes'],
            inode_usage=100-int(math.floor( fstat['ifree']/fstat['inodes']*100 ))
        )
    )


def run_module():
    # define available arguments/parameters a user can pass to the module
    module_args = dict(
        path=dict(type='path', required=True),
        unit=dict(type='str', required=False, default='MiB',
                  choices=[ 'byte', 'kB', 'KiB', 'MB', 'MiB', 'GB', 'GiB', 'TB', 'TiB', 'PB', 'PiB', 'EB', 'EiB' ]),
        free=dict(type='int', required=False, default=0),
        ifree=dict(type='int', required=False, default=0),
        delete=dict(type='list', required=False)
    )

    # the AnsibleModule object will be our abstraction working with Ansible
    module = AnsibleModule(
        argument_spec=module_args,
        supports_check_mode=True
    )

    # get the arguments
    params = module.params
    path = params.get('path')
    b_path = to_bytes(path, errors='surrogate_or_strict')
    unit = params.get('unit')
    unit_multiple = unit_map[unit]
    want_free = params.get('free')
    want_ifree = params.get('ifree')
    delete = [d.strip() for d in params.get('delete')] if params.get('delete') else False

    # get free space information
    fstat = get_free(b_path)
    # do we meet the desired free space?
    have_space = run_check(fstat, unit_multiple, want_free, want_ifree)

    # if we have the desired free space we're done
    if have_space:
        result = build_result(False, fstat, unit_multiple)
        module.exit_json(**result)


    # the next step involves removing files to try to meet the free space requirements
    # don't want to do that if running in check_mode so we fail
    # can't do that if no files/paths to remove were specified, that's a failure
    if module.check_mode or not delete:
        result = build_result(False, fstat, unit_multiple)
        module.fail_json(msg='Not enough free space: have ' + str(result['stat']['free'])
                             + ' ' + unit + ', want ' + str(want_free) + ' ' + unit,
                         **result)


    # remove the provided files/paths to free up some space
    files_cleared = remove_files(path, delete)

    # get free space information
    fstat = get_free(b_path)
    # do we meet the desired free space?
    have_space = run_check(fstat, unit_multiple, want_free, want_ifree)

    # get the final result and exit
    result = build_result(files_cleared, fstat, unit_multiple)
    if not have_space:
        module.fail_json(msg='Not enough free space: have ' + str(result['stat']['free'])
                             + ' ' + unit + ', want ' + str(want_free) + ' ' + unit,
                         **result)
    module.exit_json(**result)


def main():
    run_module()

if __name__ == '__main__':
    main()
