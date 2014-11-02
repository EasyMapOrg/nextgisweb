# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from ..component import Component

from .ident import COMP_ID
from .model import Base


@Component.registry.register
class ResourceMetadataComponent(Component):
    identity = COMP_ID
    metadata = Base.metadata
