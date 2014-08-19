# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import uuid
import types
import zipfile
import tempfile
import shutil
import ctypes
import operator
from distutils.version import LooseVersion

from zope.interface import implements
import osgeo
from osgeo import ogr, osr

from sqlalchemy import event
import geoalchemy as ga
import sqlalchemy.sql as sql

from .. import db
from ..resource import (
    Resource,
    DataScope,
    Serializer,
    SerializedProperty as SP,
    SerializedRelationship as SR)
from ..resource.exception import ValidationError
from ..env import env
from ..geometry import geom_from_wkb, box
from ..models import declarative_base, DBSession
from ..layer import SpatialLayerMixin

from ..feature_layer import (
    Feature,
    FeatureSet,
    LayerField,
    LayerFieldsMixin,
    GEOM_TYPE,
    FIELD_TYPE,
    IFeatureLayer,
    IWritableFeatureLayer,
    IFeatureQuery,
    IFeatureQueryFilterBy,
    IFeatureQueryLike)

GEOM_TYPE_GA = (ga.MultiPoint, ga.MultiLineString, ga.MultiPolygon)
GEOM_TYPE_DB = ('MULTIPOINT', 'MULTILINESTRING', 'MULTIPOLYGON')
GEOM_TYPE_OGR = (ogr.wkbPoint, ogr.wkbLineString, ogr.wkbPolygon)
GEOM_TYPE_DISPLAY = (u"Точка", u"Линия", u"Полигон")

FIELD_TYPE_DB = (
    db.Integer,
    db.Float,
    db.Unicode,
    db.Date,
    db.Time,
    db.DateTime)

FIELD_TYPE_OGR = (
    ogr.OFTInteger,
    ogr.OFTReal,
    ogr.OFTString,
    ogr.OFTDate,
    ogr.OFTTime,
    ogr.OFTDateTime)

_GEOM_OGR_2_TYPE = dict(zip(GEOM_TYPE_OGR, GEOM_TYPE.enum))
_GEOM_TYPE_2_DB = dict(zip(GEOM_TYPE.enum, GEOM_TYPE_DB))
_GEOM_TYPE_2_GA = dict(zip(GEOM_TYPE_DB, GEOM_TYPE_GA))

_FIELD_TYPE_2_ENUM = dict(zip(FIELD_TYPE_OGR, FIELD_TYPE.enum))
_FIELD_TYPE_2_DB = dict(zip(FIELD_TYPE.enum, FIELD_TYPE_DB))

Base = declarative_base()


class FieldDef(object):

    def __init__(self, key, keyname, datatype, uuid):
        self.key = key
        self.keyname = keyname
        self.datatype = datatype
        self.uuid = uuid


class TableInfo(object):

    def __init__(self, srs_id):
        self.srs_id = srs_id
        self.metadata = None
        self.table = None
        self.model = None

    @classmethod
    def from_ogrlayer(cls, ogrlayer, srs_id, strdecode):
        self = cls(srs_id)

        self.geometry_type = _GEOM_OGR_2_TYPE[ogrlayer.GetGeomType()]
        self.fields = []

        defn = ogrlayer.GetLayerDefn()
        for i in range(defn.GetFieldCount()):
            fld_defn = defn.GetFieldDefn(i)
            uid = str(uuid.uuid4().hex)
            self.fields.append(FieldDef(
                'fld_%s' % uid,
                fld_defn.GetNameRef(),
                _FIELD_TYPE_2_ENUM[fld_defn.GetType()],
                uid
            ))

        return self

    @classmethod
    def from_layer(cls, layer):
        self = cls(layer.srs_id)

        self.geometry_type = layer.geometry_type

        self.fields = []
        for f in layer.fields:
            self.fields.append(FieldDef(
                'fld_%s' % f.fld_uuid,
                f.keyname,
                f.datatype,
                f.fld_uuid
            ))

        return self

    def __getitem__(self, keyname):
        for f in self.fields:
            if f.keyname == keyname:
                return f

    def setup_layer(self, layer):
        layer.geometry_type = self.geometry_type

        layer.fields = []
        for f in self.fields:
            layer.fields.append(VectorLayerField(
                keyname=f.keyname,
                datatype=f.datatype,
                display_name=f.keyname,
                fld_uuid=f.uuid
            ))

    def setup_metadata(self, tablename=None):
        metadata = db.MetaData(schema='vector_layer' if tablename else None)
        geom_fldtype = _GEOM_TYPE_2_DB[self.geometry_type]

        class model(object):
            def __init__(self, **kwargs):
                for k, v in kwargs.iteritems():
                    setattr(self, k, v)

        table = db.Table(
            tablename if tablename else ('lvd_' + str(uuid.uuid4().hex)),
            metadata, db.Column('id', db.Integer, primary_key=True),
            ga.GeometryExtensionColumn('geom', _GEOM_TYPE_2_GA[
                geom_fldtype](2, srid=self.srs_id)),
            *map(lambda (fld): db.Column(fld.key, _FIELD_TYPE_2_DB[
                fld.datatype]), self.fields)
        )

        ga.GeometryDDL(table)

        db.mapper(model, table)

        self.metadata = metadata
        self.table = table
        self.model = model

    def load_from_ogr(self, ogrlayer, strdecode):
        source_osr = ogrlayer.GetSpatialRef()
        target_osr = osr.SpatialReference()
        target_osr.ImportFromEPSG(self.srs_id)

        transform = osr.CoordinateTransformation(source_osr, target_osr)

        feature = ogrlayer.GetNextFeature()
        fid = 0
        while feature:
            fid += 1
            geom = feature.GetGeometryRef()

            if geom.GetGeometryType() == ogr.wkbPoint:
                geom = ogr.ForceToMultiPoint(geom)
            elif geom.GetGeometryType() == ogr.wkbLineString:
                geom = ogr.ForceToMultiLineString(geom)
            elif geom.GetGeometryType() == ogr.wkbPolygon:
                geom = ogr.ForceToMultiPolygon(geom)

            geom.Transform(transform)

            fld_values = dict()
            for i in range(feature.GetFieldCount()):
                fld_type = feature.GetFieldDefnRef(i).GetType()
                fld_value = None
                if fld_type == ogr.OFTInteger:
                    fld_value = feature.GetFieldAsInteger(i)
                elif fld_type == ogr.OFTReal:
                    fld_value = feature.GetFieldAsDouble(i)
                elif fld_type == ogr.OFTString:
                    fld_value = strdecode(feature.GetFieldAsString(i))

                fld_values[self[feature.GetFieldDefnRef(i).GetNameRef()].key] \
                    = fld_value

            obj = self.model(fid=fid, geom=ga.WKTSpatialElement(
                str(geom), self.srs_id), **fld_values)

            DBSession.add(obj)

            feature = ogrlayer.GetNextFeature()


class VectorLayerField(Base, LayerField):
    identity = 'vector_layer'

    __tablename__ = LayerField.__tablename__ + '_' + identity
    __mapper_args__ = dict(polymorphic_identity=identity)

    id = db.Column(db.ForeignKey(LayerField.id), primary_key=True)
    fld_uuid = db.Column(db.Unicode(32), nullable=False)


class VectorLayer(Base, Resource, SpatialLayerMixin, LayerFieldsMixin):
    identity = 'vector_layer'
    cls_display_name = u"Векторный слой"

    __scope__ = DataScope

    implements(IFeatureLayer, IWritableFeatureLayer)

    tbl_uuid = db.Column(db.Unicode(32), nullable=False)
    geometry_type = db.Column(db.Enum(*GEOM_TYPE.enum), nullable=False)

    @classmethod
    def check_parent(self, parent):
        return parent.cls == 'resource_group'

    @property
    def _tablename(self):
        return 'layer_%s' % self.tbl_uuid

    def setup_from_ogr(self, ogrlayer, strdecode):
        tableinfo = TableInfo.from_ogrlayer(ogrlayer, self.srs.id, strdecode)
        tableinfo.setup_layer(self)

        tableinfo.setup_metadata(tablename=self._tablename)
        tableinfo.metadata.create_all(bind=DBSession.connection())

        self.tableinfo = tableinfo

    def load_from_ogr(self, ogrlayer, strdecode):
        self.tableinfo.load_from_ogr(ogrlayer, strdecode)

    def get_info(self):
        return super(VectorLayer, self).get_info() + (
            (u"Тип геометрии", dict(zip(GEOM_TYPE.enum, GEOM_TYPE_DISPLAY))[
                self.geometry_type]),
        )

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

    # IWritableFeatureLayer

    def feature_put(self, feature):
        tableinfo = TableInfo.from_layer(self)
        tableinfo.setup_metadata(tablename=self._tablename)

        obj = tableinfo.model(id=feature.id)
        for f in tableinfo.fields:
            if f.keyname in feature.fields:
                setattr(obj, f.key, feature.fields[f.keyname])

        DBSession.merge(obj)


def _vector_layer_listeners(table):
    event.listen(
        table, "after_create",
        db.DDL("CREATE SCHEMA vector_layer")
    )

    event.listen(
        table, "after_drop",
        db.DDL("DROP SCHEMA IF EXISTS vector_layer CASCADE")
    )

_vector_layer_listeners(VectorLayer.__table__)


# Инициализация БД использует table.tometadata(), однако
# SA не копирует подписки на события в этом случае.

def tometadata(self, metadata):
    result = db.Table.tometadata(self, metadata)
    _vector_layer_listeners(result)
    return result

VectorLayer.__table__.tometadata = types.MethodType(
    tometadata, VectorLayer.__table__)


def _set_encoding(encoding):
    gdal_gt_19 = LooseVersion(osgeo.__version__) >= LooseVersion('1.9')

    class encoding_section(object):

        def __init__(self, encoding):
            self.encoding = encoding

            if self.encoding and gdal_gt_19:
                # Для GDAL 1.9 и выше пытаемся установить SHAPE_ENCODING
                # через ctypes и libgdal

                # Загружаем библиотеку только в том случае,
                # если нам нужно перекодировать
                self.lib = ctypes.CDLL('libgdal.so')

                # Обертки для функций cpl_conv.h
                # см. http://www.gdal.org/cpl__conv_8h.html

                # CPLGetConfigOption
                self.get_option = self.lib.CPLGetConfigOption
                self.get_option.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
                self.get_option.restype = ctypes.c_char_p

                # CPLStrdup
                self.strdup = self.lib.CPLStrdup
                self.strdup.argtypes = [ctypes.c_char_p, ]
                self.strdup.restype = ctypes.c_char_p

                # CPLSetThreadLocalConfigOption
                # Используем именно thread local вариант функции, чтобы
                # минимизировать побочные эффекты.
                self.set_option = self.lib.CPLSetThreadLocalConfigOption
                self.set_option.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
                self.set_option.restype = None

            elif encoding:
                # Для други версий GDAL вернем функцию обертку, которая
                # умеет декодировать строки в unicode, см. __enter__
                pass

        def __enter__(self):

            if self.encoding and gdal_gt_19:
                # Для GDAL 1.9 устанавливаем значение SHAPE_ENCODING

                # Оставим копию текущего значения себе
                tmp = self.get_option('SHAPE_ENCODING', None)
                self.old_value = self.strdup(tmp)

                # Установим новое
                self.set_option('SHAPE_ENCODING', '')

                return lambda (x): x.decode(self.encoding)

            elif self.encoding:
                # Функция обертка для других версий GDAL
                return lambda (x): x.decode(self.encoding)

            return lambda (x): x

        def __exit__(self, type, value, traceback):

            if self.encoding and gdal_gt_19:
                # Возвращаем на место старое значение
                self.set_option('SHAPE_ENCODING', self.old_value)

    return encoding_section(encoding)


VE = ValidationError


class _source_attr(SP):

    def _ogrds(self, ogrds):

        if ogrds.GetLayerCount() < 1:
            raise VE("Набор данных не содержит слоёв.")

        if ogrds.GetLayerCount() > 1:
            raise VE("Набор данных содержит более одного слоя.")

        ogrlayer = ogrds.GetLayer(0)
        if not ogrlayer:
            raise VE("Не удалось открыть слой.")

        return ogrlayer

    def _ogrlayer(self, obj, ogrlayer, recode=lambda (a): a):

        if ogrlayer.GetSpatialRef() is None:
            raise VE("Не указана система координат слоя.")

        feat = ogrlayer.GetNextFeature()
        while feat:
            geom = feat.GetGeometryRef()
            if not geom:
                raise VE("Объект %d не содержит геометрии." % feat.GetFID())
            feat = ogrlayer.GetNextFeature()

        ogrlayer.ResetReading()

        obj.tbl_uuid = uuid.uuid4().hex

        with DBSession.no_autoflush:
            obj.setup_from_ogr(ogrlayer, recode)
            obj.load_from_ogr(ogrlayer, recode)

    def setter(self, srlzr, value):
        datafile, _ = env.file_upload.get_filename(value['id'])
        encoding = value.get('encoding', 'utf-8')

        iszip = zipfile.is_zipfile(datafile)

        try:
            if iszip:
                ogrfn = tempfile.mkdtemp()
                zipfile.ZipFile(datafile, 'r').extractall(path=ogrfn)
            else:
                ogrfn = datafile

            with _set_encoding(encoding) as sdecode:
                ogrds = ogr.Open(ogrfn)
                recode = sdecode

            if not ogrds:
                raise VE("Библиотеке OGR не удалось открыть файл")

            drivername = ogrds.GetDriver().GetName()

            if drivername not in ('ESRI Shapefile', ):
                raise VE("Неподдерживаемый драйвер OGR: %s" % drivername)

            ogrlayer = self._ogrds(ogrds)
            self._ogrlayer(srlzr.obj, ogrlayer, recode)

        finally:
            if iszip:
                shutil.rmtree(ogrfn)


P_DS_READ = DataScope.read
P_DS_WRITE = DataScope.write


class VectorLayerSerializer(Serializer):
    identity = VectorLayer.identity
    resclass = VectorLayer

    srs = SR(read=P_DS_READ, write=P_DS_WRITE)
    source = _source_attr(read=None, write=P_DS_WRITE)


class FeatureQueryBase(object):
    implements(
        IFeatureQuery,
        IFeatureQueryFilter,
        IFeatureQueryFilterBy,
        IFeatureQueryLike,
        IFeatureQueryIntersects)

    def __init__(self):
        self._geom = None
        self._box = None

        self._fields = None
        self._limit = None
        self._offset = None

        self._filter = None
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

    def filter(self, *args):
        self._filter = args

    def filter_by(self, **kwargs):
        self._filter_by = kwargs

    def order_by(self, *args):
        self._order_by = args

    def like(self, value):
        self._like = value

    def intersects(self, geom):
        self._intersects = geom

    def __call__(self):
        tableinfo = TableInfo.from_layer(self.layer)
        tableinfo.setup_metadata(tablename=self.layer._tablename)
        table = tableinfo.table

        columns = [table.columns.id, ]
        where = []

        if self._geom:
            columns.append(table.columns.geom.label('geom'))

        if self._box:
            columns.extend((
                db.func.st_xmin(db.text('geom')).label('box_left'),
                db.func.st_ymin(db.text('geom')).label('box_bottom'),
                db.func.st_xmax(db.text('geom')).label('box_right'),
                db.func.st_ymax(db.text('geom')).label('box_top'),
            ))

        selected_fields = []
        for f in tableinfo.fields:
            if not self._fields or f.keyname in self._fields:
                columns.append(table.columns[f.key].label(f.keyname))
                selected_fields.append(f)

        if self._filter_by:
            for k, v in self._filter_by.iteritems():
                if k == 'id':
                    where.append(table.columns.id == v)
                else:
                    where.append(table.columns[tableinfo[k].key] == v)

        if self._filter:
            l = []
            for k, o, v in self._filter:
                op = getattr(operator, o)
                if k == 'id':
                    l.append(op(table.columns.id, v))
                else:
                    l.append(op(table.columns[tableinfo[k].key], v))

            where.append(db.and_(*l))

        if self._like:
            l = []
            for f in tableinfo.fields:
                if f.datatype == FIELD_TYPE.STRING:
                    l.append(table.columns[f.key].ilike(
                        '%' + self._like + '%'))

            where.append(db.or_(*l))

        if self._intersects:
            geom = ga.WKTSpatialElement(
                self._intersects.wkt,
                self._intersects.srid)
            where.append(geom.intersects(table.columns.geom))

        class QueryFeatureSet(FeatureSet):
            fields = selected_fields
            layer = self.layer

            _geom = self._geom
            _box = self._box
            _limit = self._limit
            _offset = self._offset

            def __iter__(self):
                query = sql.select(
                    columns,
                    whereclause=db.and_(*where),
                    limit=self._limit,
                    offset=self._offset,
                    order_by=table.columns.id,
                )
                rows = DBSession.connection().execute(query)
                for row in rows:
                    fdict = dict([(f.keyname, row[f.keyname])
                                  for f in selected_fields])
                    yield Feature(
                        layer=self.layer,
                        id=row.id,
                        fields=fdict,
                        geom=(geom_from_wkb(str(row.geom.geom_wkb))
                              if self._geom else None),
                        box=box(
                            row.box_left, row.box_bottom,
                            row.box_right, row.box_top
                        ) if self._box else None
                    )

            @property
            def total_count(self):
                query = sql.select(
                    [db.func.count(table.columns.id), ],
                    whereclause=db.and_(*where)
                )
                res = DBSession.connection().execute(query)
                for row in res:
                    return row[0]

        return QueryFeatureSet()
