// static/js/select2-init.js
$(document).ready(function() {
    $('.select2-ajax-search').select2({
        ajax: {
            url: '/search-items/', // Use your defined Django URL
            dataType: 'json',
            delay: 250,
            data: function(params) {
                return { q: params.term }; // 'q' is the query parameter
            },
            processResults: function(data) {
                return { results: data.results }; // Return the formatted results
            },
            cache: true
        },
        placeholder: 'Start typing to search...',
        minimumInputLength: 1
    });
});