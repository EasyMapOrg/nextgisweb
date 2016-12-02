<%inherit file='obj.mako' />

<%def name="head()">
    <% import json %>
    <script type="text/javascript">
        var formParams = ${dict(widget.widget_params(), url="") | json.dumps, n};

        var form;

        require([
            "dojo/_base/declare",
            "dojo/ready",
            ${ widget.widget_module() | json.dumps, n },
            "ngw-pyramid/modelWidget/FormMixin",
            "ngw-pyramid/modelWidget/CompositeTitlePaneMixin"
        ], function (declare, ready, Base, FormMixin, CompositeTitlePaneMixin) {
            var FormClass = declare([Base, FormMixin, CompositeTitlePaneMixin]);
            form = new FormClass(formParams);
            ready(function() {
                form.placeAt('form').startup();
            });
        });
    </script>
</%def>

<div id="form"></div>
