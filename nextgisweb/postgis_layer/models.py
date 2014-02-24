# -*- coding: utf-8 -*-
from zope.interface import implements

import sqlalchemy as sa
from sqlalchemy import sql, func

from ..models import declarative_base
from ..env import env
from ..geometry import geom_from_wkt, box
from ..layer import Layer, SpatialLayerMixin
from ..feature_layer import (
    Feature,
    FeatureSet,
    LayerField,
    LayerFieldsMixin,
    GEOM_TYPE,
    FIELD_TYPE,
    IFeatureLayer,
    IFeatureQuery,
    IFeatureQueryFilterBy,
    IFeatureQueryLike,
)

Base = declarative_base()


GEOM_TYPE_DISPLAY = (u"Точка", u"Линия", u"Полигон")


@Layer.registry.register
class PostgisLayer(Base, Layer, SpatialLayerMixin, LayerFieldsMixin):
    implements(IFeatureLayer)

    __tablename__ = 'postgis_layer'

    identity = __tablename__
    cls_display_name = u"Cлой PostGIS"

    layer_id = sa.Column(sa.Integer, sa.ForeignKey(Layer.id), primary_key=True)
    connection = sa.Column(sa.Unicode, nullable=False)
    schema = sa.Column(sa.Unicode, default=u'public', nullable=False)
    table = sa.Column(sa.Unicode, nullable=False)
    column_id = sa.Column(sa.Unicode, nullable=False)
    column_geom = sa.Column(sa.Unicode, nullable=False)
    geometry_type = sa.Column(sa.Enum(*GEOM_TYPE.enum, native_enum=False), nullable=False)
    geometry_srid = sa.Column(sa.Integer, nullable=False)

    __mapper_args__ = dict(
        polymorphic_identity=identity,
    )

    def get_info(self):
        return super(PostgisLayer, self).get_info() + (
            (u"Тип геометрии", dict(zip(GEOM_TYPE.enum, GEOM_TYPE_DISPLAY))[self.geometry_type]),
            (u"Подключение", self.connection),
            (u"Схема", self.schema),
            (u"Таблица", self.table),
            (u"Поле ID", self.column_id),
            (u"Поле геометрии", self.column_geom),
        )

    @property
    def source(self):
        source_meta = super(PostgisLayer, self).source
        source_meta.update(dict(
            schema=self.schema,
            table=self.table,
            column_id=self.column_id,
            column_geom=self.column_geom,
            geometry_type=self.geometry_type)
        )
        return source_meta

    def setup(self):
        fdata = dict()
        for f in self.fields:
            fdata[f.keyname] = dict(
                display_name=f.display_name,
                grid_visibility=f.grid_visibility)

        for f in list(self.fields):
            self.fields.remove(f)

        self.feature_label_field = None

        conn = env.postgis_layer.connection[self.connection].connect()
        try:
            result = conn.execute(
                """SELECT type, srid FROM geometry_columns
                WHERE f_table_schema = %s
                    AND f_table_name = %s
                    AND f_geometry_column = %s""",
                self.schema,
                self.table,
                self.column_geom
            )

            row = result.first()
            if row:
                self.geometry_srid = row['srid']

                table_geometry_type = row['type'].replace('MULTI', '')

                # Если тип геометрии не указан в базе,
                # то он должен быть указан заранее
                assert not (
                    table_geometry_type == 'GEOMETRY'
                    and self.geometry_type is None
                )

                # Если тип геометрии указан в базе,
                # то заранее не должен быть указан другой
                assert not (
                    self.geometry_type is not None
                    and table_geometry_type != 'GEOMETRY'
                    and self.geometry_type != table_geometry_type
                )

                if self.geometry_type is None:
                    self.geometry_type = table_geometry_type

            result = conn.execute(
                """SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s
                    AND table_name = %s
                ORDER BY ordinal_position""",
                self.schema,
                self.table
            )
            for row in result:
                if row['column_name'] == self.column_id:
                    assert row['data_type'] == 'integer'
                elif row['column_name'] == self.column_geom:
                    pass
                elif row['column_name'] in ('id', 'geom'):
                    # FIXME: На данный момент наличие полей id или
                    # geom полностью ломает векторный слой
                    pass
                else:
                    datatype = None
                    if row['data_type'] == 'integer':
                        datatype = FIELD_TYPE.INTEGER
                    elif row['data_type'] == 'double precision':
                        datatype = FIELD_TYPE.REAL
                    elif row['data_type'] == 'character varying':
                        datatype = FIELD_TYPE.STRING
                    elif row['data_type'] == 'uuid':
                        datatype = FIELD_TYPE.STRING

                    if datatype is not None:
                        fopts = dict(display_name=row['column_name'])
                        fopts.update(fdata.get(row['column_name'], dict()))
                        self.fields.append(LayerField(
                            keyname=row['column_name'],
                            datatype=datatype,
                            **fopts))
        finally:
            conn.close()

    # IFeatureLayer

    @property
    def feature_query(self):

        class BoundFeatureQuery(FeatureQueryBase):
            layer = self

        return BoundFeatureQuery

    def field_by_keyname(self, keyname):
        for f in self.fields:
            if f.keyname == keyname:
                return f

        raise KeyError("Field '%s' not found!" % keyname)


class FeatureQueryBase(object):
    implements(IFeatureQuery, IFeatureQueryFilterBy, IFeatureQueryLike)

    def __init__(self):
        self._geom = None
        self._box = None

        self._fields = None
        self._limit = None
        self._offset = None

        self._filter_by = None
        self._like = None
        self._intersects = None

    def geom(self):
        self._geom = True

    def box(self):
        self._box = True

    def fields(self, *args):
        self._fields = args

    def limit(self, limit, offset=0):
        self._limit = limit
        self._offset = offset

    def filter_by(self, **kwargs):
        self._filter_by = kwargs

    def order_by(self, *args):
        self._order_by = args

    def like(self, value, column=None):
        self._like = value
        self._like_column = column

    def intersects(self, geom):
        self._intersects = geom

    def __call__(self):
        tab = sql.table(self.layer.table)
        tab.schema = self.layer.schema

        tab.quote = True
        tab.quote_schema = True

        select = sa.select([], tab)

        def addcol(col):
            select.append_column(col)

        idcol = sql.column(self.layer.column_id)
        addcol(idcol.label('id'))

        geomcol = sql.column(self.layer.column_geom)
        geomexpr = sa.func.st_transform(geomcol, self.layer.srs_id)

        if self._geom:
            addcol(sa.func.st_astext(geomexpr).label('geom'))

        fieldmap = []
        for idx, fld in enumerate(self.layer.fields, start=1):
            if not self._fields or fld.keyname in self._fields:
                clabel = 'f%d' % idx
                addcol(sql.column(fld.keyname).label(clabel))
                fieldmap.append((fld.keyname, clabel))

        if self._filter_by:
            for k, v in self._filter_by.iteritems():
                if k == 'id':
                    select.append_whereclause(idcol == v)
                else:
                    select.append_whereclause(sql.column(k) == v)

        if self._like:
            l = []
            for fld in self.layer.fields:
                if fld.datatype == FIELD_TYPE.STRING:
                    if fld.keyname == self._like_column or self._like_column is None:
                        l.append(sql.cast(
                            sql.column(fld.keyname),
                            sa.Unicode).ilike(
                            '%' + self._like + '%'))

            select.append_whereclause(sa.or_(*l))

        if self._intersects:
            intgeom = sa.func.st_setsrid(sa.func.st_geomfromtext(
                self._intersects.wkt), self._intersects.srid)
            select.append_whereclause(sa.func.st_intersects(
                geomcol, sa.func.st_transform(
                    intgeom, self.layer.geometry_srid)))

        if self._box:
            addcol(func.st_xmin(geomexpr).label('box_left'))
            addcol(func.st_ymin(geomexpr).label('box_bottom'))
            addcol(func.st_xmax(geomexpr).label('box_right'))
            addcol(func.st_ymax(geomexpr).label('box_top'))

        gt = self.layer.geometry_type
        select.append_whereclause(sa.func.geometrytype(sql.column(
            self.layer.column_geom)).in_((gt, 'MULTI' + gt)))

        select.append_order_by(idcol)

        class QueryFeatureSet(FeatureSet):
            layer = self.layer

            _geom = self._geom
            _box = self._box
            _fields = self._fields
            _limit = self._limit
            _offset = self._offset

            def __iter__(self):
                if self._limit:
                    query = select.limit(self._limit).offset(self._offset)
                else:
                    query = select

                conn = env.postgis_layer.connection[self.layer.connection].connect()

                try:
                    for row in conn.execute(query):
                        fdict = dict([(k, row[l]) for k, l in fieldmap])

                        if self._geom:
                            geom = geom_from_wkt(row['geom'])
                        else:
                            geom = None

                        yield Feature(
                            layer=self.layer, id=row['id'],
                            fields=fdict, geom=geom,
                            box=box(
                                row['box_left'], row['box_bottom'],
                                row['box_right'], row['box_top']
                            ) if self._box else None
                        )

                finally:
                    conn.close()

            @property
            def total_count(self):
                conn = env.postgis_layer.connection[self.layer.connection].connect()
                try:
                    result = conn.execute(sa.select(
                        [sql.text('COUNT(id)'), ],
                        from_obj=select.alias('all')))
                    for row in result:
                        return row[0]
                finally:
                    conn.close()

        return QueryFeatureSet()
