try:
    from .action import StencilframerAction
except ImportError:
    StencilframerAction = None


if StencilframerAction is not None:
    StencilframerAction().register()
