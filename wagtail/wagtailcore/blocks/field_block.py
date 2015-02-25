from __future__ import absolute_import, unicode_literals

import datetime

from django import forms
from django.template.loader import render_to_string
from django.utils.encoding import force_text
from django.utils.dateparse import parse_date, parse_time, parse_datetime
from django.utils.functional import cached_property
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from wagtail.wagtailcore.rich_text import expand_db_html

from .base import Block


class FieldBlock(Block):
    class Meta:
        default = None

    def render_form(self, value, prefix='', errors=None):
        widget = self.field.widget

        if self.label:
            label_html = format_html(
                """<label for={label_id}>{label}</label> """,
                label_id=widget.id_for_label(prefix), label=self.label
            )
        else:
            label_html = ''

        widget_attrs = {'id': prefix, 'placeholder': self.label}

        if hasattr(widget, 'render_with_errors'):
            widget_html = widget.render_with_errors(prefix, value, attrs=widget_attrs, errors=errors)
            widget_has_rendered_errors = True
        else:
            widget_html = widget.render(prefix, value, attrs=widget_attrs)
            widget_has_rendered_errors = False

        return render_to_string('wagtailadmin/block_forms/field.html', {
            'name': self.name,
            'label': self.label,
            'classes': self.meta.classname,
            'widget': widget_html,
            'label_tag': label_html,
            'field': self.field,
            'errors': errors if (not widget_has_rendered_errors) else None
        })

    def value_from_datadict(self, data, files, prefix):
        return self.to_python(self.field.widget.value_from_datadict(data, files, prefix))

    def clean(self, value):
        return self.field.clean(value)


class CharBlock(FieldBlock):
    def __init__(self, required=True, help_text=None, max_length=None, min_length=None, **kwargs):
        # CharField's 'label' and 'initial' parameters are not exposed, as Block handles that functionality natively (via 'label' and 'default')
        self.field = forms.CharField(required=required, help_text=help_text, max_length=max_length, min_length=min_length)
        super(CharBlock, self).__init__(**kwargs)

    def get_searchable_content(self, value):
        return [force_text(value)]


class URLBlock(FieldBlock):
    def __init__(self, required=True, help_text=None, max_length=None, min_length=None, **kwargs):
        self.field = forms.URLField(required=required, help_text=help_text, max_length=max_length, min_length=min_length)
        super(URLBlock, self).__init__(**kwargs)


class DateBlock(FieldBlock):
    def __init__(self, required=True, help_text=None, **kwargs):
        self.field_options = {'required': required, 'help_text': help_text}
        super(DateBlock, self).__init__(**kwargs)

    @cached_property
    def field(self):
        from wagtail.wagtailadmin.widgets import AdminDateInput
        field_kwargs = {'widget': AdminDateInput}
        field_kwargs.update(self.field_options)
        return forms.DateField(**field_kwargs)

    def to_python(self, value):
        # Serialising to JSON uses DjangoJSONEncoder, which converts date/time objects to strings.
        # The reverse does not happen on decoding, because there's no way to know which strings
        # should be decoded; we have to convert strings back to dates here instead.
        if value is None or isinstance(value, datetime.date):
            return value
        else:
            return parse_date(value)


class TimeBlock(FieldBlock):
    def __init__(self, required=True, help_text=None, **kwargs):
        self.field_options = {'required': required, 'help_text': help_text}
        super(TimeBlock, self).__init__(**kwargs)

    @cached_property
    def field(self):
        from wagtail.wagtailadmin.widgets import AdminTimeInput
        field_kwargs = {'widget': AdminTimeInput}
        field_kwargs.update(self.field_options)
        return forms.TimeField(**field_kwargs)

    def to_python(self, value):
        if value is None or isinstance(value, datetime.time):
            return value
        else:
            return parse_time(value)


class DateTimeBlock(FieldBlock):
    def __init__(self, required=True, help_text=None, **kwargs):
        self.field_options = {'required': required, 'help_text': help_text}
        super(DateTimeBlock, self).__init__(**kwargs)

    @cached_property
    def field(self):
        from wagtail.wagtailadmin.widgets import AdminDateTimeInput
        field_kwargs = {'widget': AdminDateTimeInput}
        field_kwargs.update(self.field_options)
        return forms.DateTimeField(**field_kwargs)

    def to_python(self, value):
        if value is None or isinstance(value, datetime.datetime):
            return value
        else:
            return parse_datetime(value)


class RichTextBlock(FieldBlock):
    @cached_property
    def field(self):
        from wagtail.wagtailcore.fields import RichTextArea
        return forms.CharField(widget=RichTextArea)

    def render_basic(self, value):
        return mark_safe('<div class="rich-text">' + expand_db_html(value) + '</div>')

    def get_searchable_content(self, value):
        return [force_text(value)]


class RawHTMLBlock(FieldBlock):
    def __init__(self, required=True, help_text=None, max_length=None, min_length=None, **kwargs):
        self.field = forms.CharField(
            required=required, help_text=help_text, max_length=max_length, min_length=min_length,
            widget = forms.Textarea)
        super(RawHTMLBlock, self).__init__(**kwargs)

    def render_basic(self, value):
        return mark_safe(value)  # if it isn't safe, that's the site admin's problem for allowing raw HTML blocks in the first place...

    class Meta:
        icon = 'code'


class ChooserBlock(FieldBlock):
    def __init__(self, required=True, **kwargs):
        self.required=required
        super(ChooserBlock, self).__init__(**kwargs)

    """Abstract superclass for fields that implement a chooser interface (page, image, snippet etc)"""
    @cached_property
    def field(self):
        return forms.ModelChoiceField(queryset=self.target_model.objects.all(), widget=self.widget, required=self.required)

    def to_python(self, value):
        if value is None or isinstance(value, self.target_model):
            return value
        else:
            try:
                return self.target_model.objects.get(pk=value)
            except self.target_model.DoesNotExist:
                return None

    def get_prep_value(self, value):
        if isinstance(value, self.target_model):
            return value.id
        else:
            return value

    def clean(self, value):
        # ChooserBlock works natively with model instances as its 'value' type (because that's what you
        # want to work with when doing front-end templating), but ModelChoiceField.clean expects an ID
        # as the input value (and returns a model instance as the result). We don't want to bypass
        # ModelChoiceField.clean entirely (it might be doing relevant validation, such as checking page
        # type) so we convert our instance back to an ID here. It means we have a wasted round-trip to
        # the database when ModelChoiceField.clean promptly does its own lookup, but there's no easy way
        # around that...
        if isinstance(value, self.target_model):
            value = value.pk
        return super(ChooserBlock, self).clean(value)

class PageChooserBlock(ChooserBlock):
    @cached_property
    def target_model(self):
        from wagtail.wagtailcore.models import Page  # TODO: allow limiting to specific page types
        return Page

    @cached_property
    def widget(self):
        from wagtail.wagtailadmin.widgets import AdminPageChooser
        return AdminPageChooser

    def render_basic(self, value):
        if value:
            return format_html('<a href="{0}">{1}</a>', value.url, value.title)
        else:
            return ''


# Ensure that the blocks defined here get deconstructed as wagtailcore.blocks.FooBlock
# rather than wagtailcore.blocks.field.FooBlock
block_classes = [
    FieldBlock, CharBlock, URLBlock, RichTextBlock, RawHTMLBlock, ChooserBlock, PageChooserBlock,
    DateBlock, TimeBlock, DateTimeBlock,
]
DECONSTRUCT_ALIASES = {
    cls: 'wagtail.wagtailcore.blocks.%s' % cls.__name__
    for cls in block_classes
}
__all__ = [cls.__name__ for cls in block_classes]