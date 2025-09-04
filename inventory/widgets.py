from django import forms

class Select2Widget(forms.Select):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add a CSS class to target in your JavaScript
        self.attrs['class'] = 'select2-ajax-search' 

    class Media:
        # Paths to your static files (jQuery, Select2)
        js = (
            'https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.0/jquery.min.js',
            'https://cdn.jsdelivr.net/npm/select2@4.1.0-rc.0/dist/js/select2.min.js',
        )
        css = {
            'all': (
                'https://cdn.jsdelivr.net/npm/select2@4.1.0-rc.0/dist/css/select2.min.css',
            )
        }