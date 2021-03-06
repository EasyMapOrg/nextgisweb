# -*- coding: utf-8 -*-

'''Utilities to convert nextgisweb layers to featureserver datasources
'''

from __future__ import unicode_literals

from osgeo import ogr
import shapely

from bunch import Bunch

import geojson

from nextgisweb.feature_layer import Feature as NgwFeature
from nextgisweb.feature_layer import IWritableFeatureLayer, GEOM_TYPE, FIELD_TYPE
from nextgisweb.geometry import box

from .third_party.FeatureServer.DataSource import DataSource
from .third_party.vectorformats.Feature import Feature

from .third_party.FeatureServer.WebFeatureService.Response.InsertResult import InsertResult
from .third_party.FeatureServer.WebFeatureService.Response.UpdateResult import UpdateResult
from .third_party.FeatureServer.WebFeatureService.Response.DeleteResult import DeleteResult

from .third_party.FeatureServer.Exceptions.OperationProcessingFailedException import OperationProcessingFailedException
from .third_party.FeatureServer.Exceptions.BaseException import BaseException

class NextgiswebDatasource(DataSource):

    '''Class to convert nextgislayer to featureserver datasource
    '''

    def __init__(self, name,  **kwargs):
        DataSource.__init__(self, name, **kwargs)
        self.fid_col = 'id'
        self.layer = kwargs["layer"]
        self.title = kwargs["title"]
        self.query = None       # To define later (to reduce number of requests to DB at this stage)
        self.type = 'NextgisWeb'
        if 'attribute_cols' in kwargs:
            self.attribute_cols = kwargs['attribute_cols'].split(',')
        else:
            self.attribute_cols = None      # Назначим потом (чтобы не производить лишних запросов к БД на этом этапе)

        if 'maxfeatures' in kwargs and kwargs['maxfeatures'] is not None:
            try:
                self.maxfeatures = int(kwargs['maxfeatures'])
            except:
                raise BaseException(
                    message="Maxfearutes (count) paramether can't be cast to integer: %s" % (kwargs['maxfeatures']))

    @property
    def srid_out(self):
        return self.layer.srs_id

    @property
    def default_maxfeatures(self):
        if hasattr(self, 'maxfeatures'):
            return self.maxfeatures
        return None

    @property
    def geometry_type(self):

        if self.layer.geometry_type == GEOM_TYPE.POINT:
            geometry_type = 'Point'
        elif self.layer.geometry_type == GEOM_TYPE.LINESTRING:
            geometry_type = 'Line'
        elif self.layer.geometry_type == GEOM_TYPE.POLYGON:
            geometry_type = 'Polygon'
        # MultiGeom
        elif self.layer.geometry_type == GEOM_TYPE.MULTIPOINT:
            geometry_type = 'MultiPoint'
        elif self.layer.geometry_type == GEOM_TYPE.MULTILINESTRING:
            geometry_type = 'MultiLine'
        elif self.layer.geometry_type == GEOM_TYPE.MULTIPOLYGON:
            geometry_type = 'MultiPolygon'
        else:
            raise NotImplementedError

        return geometry_type

    @property
    def geom_col(self):

        # Setup geometry column name. But some resources do not provide the
        # name
        try:
            geom_col = self.layer.column_geom
        except AttributeError:
            geom_col = u'geom'

        return geom_col

    @property
    def writable(self):
        # Can we edit this layer
        return IWritableFeatureLayer.providedBy(self.layer)

    def _setup_query(self):
        if self.query is None:
            self.query = self.layer.feature_query()

    def set_attribute_cols(self):
        columns = [f.keyname for f in self.layer.fields]
        self.attribute_cols = columns

    def get_attribute_cols(self):
        if self.attribute_cols is None:
            self.set_attribute_cols()

        return self.attribute_cols

    # FeatureServer.DataSource
    def select(self, params):
        if self.query is None:
            self._setup_query()

        self.query.filter_by()

        # Startfeature+maxfeature
        if params.startfeature is None:
            params.startfeature = 0
        if params.maxfeatures:
            maxfeatures = params.maxfeatures
        else:
            maxfeatures = self.maxfeatures

        self.query.limit(maxfeatures, params.startfeature)

        # BBOX
        if params.bbox:
            coords = params.bbox['coords']
            srs_id = params.bbox['srs_id'] if 'srs_id' in params.bbox else self.srid_out
            geom = box(*coords, srid=srs_id)
            self.query.intersects(geom)

        srid = params.srsname if params.srsname else self.srid_out
        self.query.srs(Bunch({'id': srid}))

        self.query.geom()
        result = self.query()

        features = []
        fields_checked = False
        for row in result:
            # Check if names contains characters that can't be used in XML tags
            if not fields_checked:
                for field_name in row.fields:
                    if '<' in field_name or '>' in field_name or '&' in field_name or '@' in field_name:
                        raise OperationProcessingFailedException(
                            message='Field name %s contains unsupported symbol' % (field_name, ))
                fields_checked = True

            feature = Feature(id=row.id, props=row.fields, srs=self.srid_out)
            feature.geometry_attr = self.geom_col
            geom = geojson.dumps(row.geom)

            # featureserver.feature.geometry is a dict, so convert str->dict:
            feature.set_geo(geojson.loads(geom))
            features.append(feature)

        return features

    def update(self, action):
        """ action.wfsrequest stores object Transaction.Update
        need to parse it and work on it
        """
        if not self.writable:
            return None

        try:
            if action.wfsrequest is not None:
                if self.query is None:
                    self._setup_query()

                data = action.wfsrequest.getStatement(self)
                data = geojson.loads(data)

                id = data[self.fid_col]

                self.query.filter_by(id=id)
                self.query.geom()
                result = self.query()

                # Update attributes if needed
                feat = result.one()
                for field_name in feat.fields:
                    if data.has_key(field_name):
                        if data[field_name] == '':
                            feat.fields[field_name] = None
                        else:
                            feat.fields[field_name] = data[field_name]
                # Update geometries if needed:
                if data.has_key('geom'):
                    geom = self._geom_from_gml(data['geom'])
                    feat.geom = geom

                self.layer.feature_put(feat)

                return UpdateResult(id, "")
        except:
            raise OperationProcessingFailedException(
                        message="Can't update feature (data=%s)" % (data, ))

        return None

    def insert(self, action):
        """ action.wfsrequest stores Transaction.Insert object
        need to parse it and work on it
        """
        if not self.writable:
            return None

        # import ipdb; ipdb.set_trace()
        try:
            if action.wfsrequest is not None:
                # import ipdb; ipdb.set_trace()
                data = action.wfsrequest.getStatement(self)

                feature_dict = geojson.loads(data)

                # geometry should be in shapely,
                # as ngw Feature stores geometries like that
                # import ipdb; ipdb.set_trace()
                geom = self._geom_from_gml(feature_dict[self.geom_col])

                # Geometry field in attributes is not needed anymore
                feature_dict.pop(self.geom_col)

                feature = NgwFeature(fields=feature_dict, geom=geom)

                feature_id = self.layer.feature_create(feature)

                id = str(feature_id)
                return InsertResult(id, action.handle, action.layer)
        except:
            raise OperationProcessingFailedException(
                        message="Can't insert new feature")

        return None

    def delete(self, action, response=None):
        """ action.wfsrequest stores Transaction.Delete object
        need to parse it and work on it
        """
        if action.wfsrequest is not None:
            try:
                data = action.wfsrequest.getStatement(self)
                data = geojson.loads(data)
                for id in data:
                    self.layer.feature_delete(id)
            except:
                raise OperationProcessingFailedException(
                    message="Can't delete feature (id=%s)" % (id, ))

            if len(data) == 0:
                raise OperationProcessingFailedException(
                    message="Empty list of Feature-id is recieved. Check format of the transaction."
                )

            return DeleteResult(action.id, "")

        return None

    def getAttributeDescription(self, attribute):
        length = ''
        try:
            field = self.layer.field_by_keyname(attribute)
            field_type = field.datatype
        except KeyError:  # the attribute can be=='*', that causes KeyError
            field_type = FIELD_TYPE.STRING

        if field_type == FIELD_TYPE.INTEGER:
            field_type = 'integer'
        elif field_type == FIELD_TYPE.REAL:
            field_type = 'double'
        else:
            field_type = field_type.lower()

        return (field_type, length)

    def _geom_from_gml(self, gml):
        """Create geometry from GML.
        May be there is a better way, but I didn't find it.
        Fix it if you know how.
        """
        # import ipdb; ipdb.set_trace()
        gml = str(gml)
        # CreateGeometryFromGML can't do unicode
        ogr_geo = ogr.CreateGeometryFromGML(gml)

        return shapely.wkt.loads(ogr_geo.ExportToWkt())
