define([
    'dojo/_base/declare',
    'ngw-pyramid/i18n!webmap',
    'ngw-pyramid/hbs-i18n',
    "dojo/on",
    "dojo/dom-class",
    'dijit/form/Select',
    "openlayers/ol",
    "ngw-pyramid/utils/coordinateConverter",

    //templates
    "xstyle/css!./CoordinateSwitcher.css"
], function (
    declare,
    i18n,
    hbsI18n,
    on,
    domClass,
    Select,
    ol,
    CoordinateConverter
    ) {
    return declare([Select], {
        point: undefined,
        coordinates: {},
        options: [],
        projections: {
            initial: undefined,
            lonlat: undefined
        },
        name: "coordinate-switcher",
        class: "coordinate-switcher",
        constructor: function(options){
          declare.safeMixin(this,options);
          this._convertCoordinates();
          this._setOptions();
        },
        buildRendering: function(){
            this.inherited(arguments);
            domClass.add(this.dropDown.domNode, "coordinate-switcher__dropdown");
        },
        _convertCoordinates: function(){
            var pointLonLat = ol.proj.transform(this.point, this.projections.initial, this.projections.lonlat),
                pointLatLon=[pointLonLat[1], pointLonLat[0]];

            this.coordinates={
                DD: [
                    Math.round(pointLatLon[0]*1000000)/1000000,
                    Math.round(pointLatLon[1]*1000000)/1000000
                ],
                DMS: [
                    CoordinateConverter.DDtoDMS(pointLatLon[0], {lon: false, needString: true}),
                    CoordinateConverter.DDtoDMS(pointLatLon[1],{lon: true, needString: true})
                ],
                DM: [
                    CoordinateConverter.DDtoDM(pointLatLon[0], {lon: false, needString: true}),
                    CoordinateConverter.DDtoDM(pointLatLon[1],{lon: true, needString: true})
                ],
                degrees: [
                    Math.round(pointLatLon[0]*1000000)/1000000 + "°",
                    Math.round(pointLatLon[1]*1000000)/1000000 + "°"
                ],
                meters: [
                    Math.round(this.point[1]),
                    Math.round(this.point[0])
                ]
            };
        },
        _setOptions: function(){
            this.options = [
                {
                    label: this.coordinates.DD[0] + ", " + this.coordinates.DD[1],
                    value: this.coordinates.DD[0] + ", " + this.coordinates.DD[1],
                    format: "DD",
                    selected: !this.selectedFormat || this.selectedFormat == "DD"
                },
                {
                    label: this.coordinates.DM[0] + ", " + this.coordinates.DM[1],
                    value: this.coordinates.DM[0] + ", " + this.coordinates.DM[1],
                    format: "DM",
                    selected: this.selectedFormat == "DM"
                },
                {
                    label: this.coordinates.DMS[0] + ", " + this.coordinates.DMS[1],
                    value: this.coordinates.DMS[0] + ", " + this.coordinates.DMS[1],
                    format: "DMS",
                    selected: this.selectedFormat == "DMS"
                },
                {
                    label: this.coordinates.meters[0] + ", " + this.coordinates.meters[1],
                    value: this.coordinates.meters[0] + ", " + this.coordinates.meters[1],
                    format: "meters",
                    selected: this.selectedFormat == "meters"
                }
            ];
        },
        postCreate: function(){
            this.inherited(arguments);
        }
    });
});