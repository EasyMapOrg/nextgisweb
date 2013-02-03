# -*- coding: utf-8 -*-
from ..component import Component, require
from ..security import PERMISSION_ALL


@Component.registry.register
class LayerGroupRootComponent(Component):
    identity = 'layer_group_root'

    @require('layer_group', 'security', 'auth')
    def initialize_db(self):
        # ACL = self.env.security.ACL
        # ACLItem = self.env.security.ACLItem
        User = self.env.auth.User
        Group = self.env.auth.Group

        LayerGroup = self.env.layer_group.LayerGroup

        administrators = Group.filter_by(keyname='administrators').one()
        administrator = User.filter_by(keyname='administrator').one()
        owner = User.filter_by(keyname='owner').one()

        root = LayerGroup(
            id=0,
            owner_user=administrator,
            display_name=u"Основная группа слоёв"
        ).persist()

        root.acl.update((
            (administrators.id, 'layer_group', PERMISSION_ALL, 'allow-subtree'),
            (owner.id, 'layer_group', PERMISSION_ALL, 'allow-subtree'),
        ))
