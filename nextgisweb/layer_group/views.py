# -*- coding: utf-8 -*-
from pyramid.httpexceptions import HTTPFound

from ..views import (
    model_context,
    permalinker,
    ModelController,
    DescriptionObjectWidget,
    DeleteObjectWidget,
)
from ..object_widget import CompositeWidget
from .. import dynmenu as dm
from ..psection import PageSections
from ..object_widget import ObjectWidget

from .models import LayerGroup


class LayerGroupObjectWidget(ObjectWidget):

    def is_applicable(self):
        return self.operation in ('create', 'edit')

    def populate_obj(self):
        ObjectWidget.populate_obj(self)

        self.obj.display_name = self.data['display_name']
        self.obj.keyname = self.data['keyname']

    def validate(self):
        result = ObjectWidget.validate(self)
        self.error = []

        return result

    def widget_params(self):
        result = ObjectWidget.widget_params(self)

        if self.obj:
            result['value'] = dict(
                display_name=self.obj.display_name,
                keyname=self.obj.keyname,
            )

        return result

    def widget_module(self):
        return 'layer_group/Widget'


def setup_pyramid(comp, config):
    ACLController = comp.env.security.ACLController

    ACLController(LayerGroup).includeme(config)

    def layer_group_home(request):
        return HTTPFound(location=request.route_url('layer_group.show', id=0))

    config.add_route('layer_group', '/layer_group/').add_view(layer_group_home)

    @model_context(LayerGroup)
    def show(request, obj):
        request.require_permission(obj, 'read')

        return dict(
            obj=obj,
            sections=request.env.layer_group.layer_group_page_sections
        )

    config.add_route('layer_group.show', '/layer_group/{id:\d+}') \
        .add_view(show, renderer="psection.mako")

    @model_context(LayerGroup)
    def api_layer_group_tree(request, obj):
        request.require_permission(obj, 'read')

        def traverse(layer_group):
            return dict(
                type='layer_group', id=layer_group.id,
                display_name=layer_group.display_name,
                children=[traverse(c) for c in layer_group.children],
                layers=[
                    dict(
                        id=l.id,
                        keyname=l.keyname,
                        type='layer',
                        cls=l.cls,
                        display_name=l.display_name,
                        source=l.source,
                        styles=[
                            dict(
                                type='style', id=s.id,
                                display_name=s.display_name,
                                # Данные слоя
                                layer_id=s.layer_id,
                                layer_display_name=s.layer.display_name,
                            ) for s in l.styles
                        ]
                    ) for l in layer_group.layers
                ]
            )

        return traverse(obj)

    config.add_route(
        'api.layer_group.tree', '/api/layer_group/{id:\d+}/tree'
    ).add_view(api_layer_group_tree, renderer="json")

    permalinker(LayerGroup, 'layer_group.show')

    LayerGroup.object_widget = (
        ('layer_group', LayerGroupObjectWidget),
        ('description', DescriptionObjectWidget),
        ('delete', DeleteObjectWidget),
    )

    class LayerGroupController(ModelController):

        def create_context(self, request):
            parent = LayerGroup.filter_by(id=request.GET['parent_id']).one()
            request.require_permission(parent, 'create')

            return dict(
                parent=parent,
                owner_user=request.user,
                template_context=dict(
                    obj=parent,
                    subtitle=u"Новая группа слоёв",
                )
            )

        def edit_context(self, request):
            obj = LayerGroup.filter_by(**request.matchdict).one()
            request.require_permission(obj, 'update')

            return dict(
                obj=obj,
                template_context=dict(obj=obj),
            )

        def delete_context(self, request):
            obj = LayerGroup.filter_by(**request.matchdict).one()
            request.require_permission(obj, 'delete')

            return dict(
                obj=obj,
                template_context=dict(obj=obj),
                redirect=obj.parent.permalink(request),
            )

        def widget_class(self, context, operation):
            class Composite(CompositeWidget):
                model_class = LayerGroup

            return Composite

        def create_object(self, context):
            return LayerGroup(
                parent=context['parent'],
                owner_user=context['owner_user']
            )

        def query_object(self, context):
            return context['obj']

        def template_context(self, context):
            return context['template_context']

    LayerGroupController('layer_group') \
        .includeme(config)

    class LayerGroupDeleteMenuItem(dm.DynItem):

        def build(self, args):
            # Пропускаем основную группу слоев (корень)
            if args.obj.id == 0:
                return

            yield dm.Link(
                'operation/delete', u"Удалить",
                lambda args: args.request.route_url(
                    'layer_group.delete', id=args.obj.id))

    LayerGroup.__dynmenu__ = dm.DynMenu(
        dm.Label('add', u"Добавить"),
        dm.Link(
            'add/layer_group', u"Группа слоёв",
            lambda args: args.request.route_url(
                'layer_group.create', _query=dict(
                    parent_id=args.obj.id,
                )
            )
        ),
        dm.Label('operation', u"Операции"),
        dm.Link(
            'operation/edit', u"Редактировать",
            lambda args: args.request.route_url(
                'layer_group.edit', id=args.obj.id
            )
        ),
        dm.Link(
            'operation/acl', u"Управление доступом",
            lambda args: args.request.route_url(
                'layer_group.acl', id=args.obj.id
            )
        ),

        LayerGroupDeleteMenuItem(),
    )

    comp.layer_group_page_sections = PageSections()

    comp.layer_group_page_sections.register(
        key='children',
        priority=0,
        template="nextgisweb:templates/layer_group/section_children.mako"
    )

    comp.layer_group_page_sections.register(
        key='permissions',
        priority=90,
        title=u"Права пользователя",
        template="security/section_resource_permissions.mako"
    )
