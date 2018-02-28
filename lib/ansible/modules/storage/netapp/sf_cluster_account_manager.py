#!/usr/bin/python

# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.
#
ANSIBLE_METADATA = {'metadata_version': '1.0',
                    'status': ['preview'],
                    'supported_by': 'community'}


DOCUMENTATION = '''

module: sf_cluster_account_manager

short_description: Manage SolidFire cluster admin accounts
extends_documentation_fragment:
    - netapp.solidfire
version_added: '2.5'
author: Ryan Baker (ryan.andrew.baker@outlook.com) adapted from Sumit Kumar (sumit4@netapp.com)
description:
- Create, destroy, or update cluster admin accounts on SolidFire

options:

    state:
        description:
        - Whether the specified account should exist or not.
        required: true
        choices: ['present', 'absent']

    name:
        description:
        - Unique username for this account. (May be 1 to 64 characters in length).
        required: true

    new_name:
        description:
        - New name for the user account.
        required: false
        default: None

    attributes:
        description:
        - List of Name/Value pairs in JSON object format.
        required: false

    account_id:
        description:
        - The ID of the account to manage or update.
        required: false
        default: None

    access:
        description:
        - The level of permissions required for the account.  See API doc for accepted permissions
        required: false

'''

EXAMPLES = """
- name: Create Account
  sf_account_manager:
    hostname: "{{ solidfire_hostname }}"
    username: "{{ solidfire_username }}"
    password: "{{ solidfire_password }}"
    state: present
    name: TenantA

- name: Modify Account
  sf_account_manager:
    hostname: "{{ solidfire_hostname }}"
    username: "{{ solidfire_username }}"
    password: "{{ solidfire_password }}"
    state: present
    name: TenantA
    new_name: TenantA-Renamed

- name: Delete Account
  sf_account_manager:
    hostname: "{{ solidfire_hostname }}"
    username: "{{ solidfire_username }}"
    password: "{{ solidfire_password }}"
    state: absent
    name: TenantA-Renamed
"""

RETURN = """

"""

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.pycompat24 import get_exception
import ansible.module_utils.netapp as netapp_utils

HAS_SF_SDK = netapp_utils.has_sf_sdk()


class SolidFireClusterAccount(object):

    def __init__(self):
        self.argument_spec = netapp_utils.ontap_sf_host_argument_spec()
        self.argument_spec.update(dict(
            state=dict(required=True, choices=['present', 'absent']),
            name=dict(required=True, type='str'),
            user_password=dict(required=True, type='str'),
            access=dict(required=True, type='list'),
            account_id=dict(required=False, type='int', default=None),
            new_name=dict(required=False, type='str', default=None),
            attributes=dict(required=False, type='dict'),
            status=dict(required=False, type='str'),
        ))

        self.module = AnsibleModule(
            argument_spec=self.argument_spec,
            supports_check_mode=True
        )

        p = self.module.params

        # set up state variables
        self.state = p['state']
        self.name = p['name']
        self.user_password = p['password']
        self.account_id = p['account_id']
        self.new_name = p['new_name']
        self.attributes = p['attributes']
        self.status = p['status']

        # Check to make sure the access type is a valid type
        valid_access_type = ["accounts","administrator","clusteradmins","drives","nodes","read","reporting","repositories","volumes","write"]

        for permission in p['access']:
            if permission not in valid_access_type:
                self.module.fail_json(msg="Invalid access type:" + permission )

        self.access = p['access']

        if HAS_SF_SDK is False:
            self.module.fail_json(msg="Unable to import the SolidFire Python SDK")
        else:
            self.sfe = netapp_utils.create_sf_connection(module=self.module)

    def get_account(self):
        """
            Return account object if found

            :return: Details about the account. None if not found.
            :rtype: dict
        """
        account_list = self.sfe.list_cluster_admins()

        for account in account_list.cluster_admins:
            if account.username == self.name:
                # Update self.account_id:
                if self.account_id is not None:
                    if account.cluster_admin_id == self.account_id:
                        return account
                else:
                    self.account_id = account.cluster_admin_id
                    return account
        return None

    def create_account(self):
        try:
            self.sfe.add_cluster_admin(accept_eula="true",
                                 access=self.access,
                                 username=self.name,
                                 password=self.user_password,
                                 attributes=self.attributes)
        except:
            err = get_exception()
            self.module.fail_json(msg='Error creating account %s' % self.name, exception=str(err))

    def delete_account(self):
        try:
            self.sfe.remove_cluster_admin(cluster_admin_id=self.account_id)

        except:
            err = get_exception()
            self.module.fail_json(msg='Error deleting cluster-admin account %s' % self.account_id, exception=str(err))

    def update_account(self):
        try:
            self.sfe.modify_cluster_admin(cluster_admin_id=self.account_id,
                                    attributes=self.attributes,
                                    access=self.access)

        except:
            err = get_exception()
            self.module.fail_json(msg='Error updating account %s' % self.account_id, exception=str(err))

    def apply(self):
        changed = False
        account_exists = False
        update_account = False
        account_detail = self.get_account()

        # Read always gets added regardlress of the access requested,
        # so remove read from the result (if defined) for comparison reasons,
        # otherwise, it will detect a delta every run.  This has been reported
        # in internal netapp bug #25269
        if account_detail.access is not None:
            account_detail.access.remove("read")

        if account_detail:
            account_exists = True

            if self.state == 'absent':
                changed = True

            elif self.state == 'present':
                # Check if we need to update the account

                if account_detail.username is not None and self.new_name is not None and \
                        account_detail.username != self.new_name:
                    update_account = True
                    changed = True

                elif account_detail.attributes is not None and self.attributes is not None \
                        and account_detail.attributes != self.attributes:
                    update_account = True
                    changed = True

                elif account_detail.access is not None and self.access is not None \
                        and set(account_detail.access) != set(self.access):
                    update_account = True
                    changed = True

        else:
            if self.state == 'present':
                changed = True

        if changed:
            if self.module.check_mode:
                pass
            else:
                if self.state == 'present':
                    if not account_exists:
                        self.create_account()
                    elif update_account:
                        self.update_account()

                elif self.state == 'absent':
                    self.delete_account()

        self.module.exit_json(changed=changed)


def main():
    v = SolidFireClusterAccount()
    v.apply()

if __name__ == '__main__':
    main()
