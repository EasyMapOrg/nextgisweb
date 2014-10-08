<%inherit file="../base.mako" />

<script>
    require([
        "dojo/parser",
        "dojo/ready",
        "dijit/_WidgetBase",
        "dijit/TitlePane",
        "dijit/form/Button",
        "dojox/layout/TableContainer"
    ], function (
        parser,
        ready
    ) {
        ready(function() {
            parser.parse();
        });
    });
</script>


<div data-dojo-type="dijit/TitlePane"
    title="Аутентификация"
    style="width: 400px">

<form data-dojo-type="dojox/layout/TableContainer"
    method="POST">

    <div data-dojo-type="dijit/_WidgetBase"
        data-dojo-props="label: 'Логин'"
        style="width: 100%">

        <input name="login" style="width: 98%" />

    </div>

    <div data-dojo-type="dijit/_WidgetBase"
        data-dojo-props="label: 'Пароль'"
        style="width: 100%">
    
        <input name="password" type="password" style="width: 98%" />
    
    </div>


    <div data-dojo-type="dijit/_WidgetBase">

        <button data-dojo-type="dijit/form/Button" 
            type="submit" value="">
            Войти

        </button>

        <button data-dojo-type="dijit/form/Button" type="button" id="items">Аутентификация ADFS
            <script type="dojo/connect" data-dojo-event="onClick">
                window.location = "${request.env.auth.settings['adfs.apiurl']}?wa=wsignin1.0&wtrealm=${request.env.auth.settings['adfs.endpoint']}";
            </script>
        </button>

        ## <a href="${request.env.auth.settings['adfs.apiurl']}?wa=wsignin1.0&wtrealm=${request.env.auth.settings['adfs.endpoint']}">Аутентификация ADFS</a>
    </div>
</form>

</div>
