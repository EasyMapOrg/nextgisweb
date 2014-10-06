<%page args="dynmenu, args" />

<% from nextgisweb import dynmenu as dm %>

<div class="pure-menu pure-menu-open" style="border-color: #dfdfdf;"><ul>
%for item in dynmenu.build(args):
    %if isinstance(item, dm.Label):
        <li class="pure-menu-heading">${item.label}</li>
    %elif isinstance(item, dm.Link):
        <% url = item.url(args) %>
        <li class="${'pure-menu-selected' if url == request.url else ''}">
            <a href="${url}">${item.label}</a>
        </li>
    %endif
%endfor
</ul></div>