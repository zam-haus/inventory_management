let add_image_button = document.querySelector('#add_image_button')
let image_count_input = document.querySelector("#id_itemimage_set-TOTAL_FORMS")
let image_placeholder_path = document.querySelector('#placeholder_path').value;

add_image_button?.addEventListener('click', function() {
	let idx = Number(image_count_input.value);
	image_count_input.value = idx +1;
	let original = document.querySelector(".itemimage_set_item input[type='file']:not([disabled])").closest(".itemimage_set_item");
	let clone = original.cloneNode(true);
	
	//empty all inputs
	clone.querySelectorAll("img").forEach(image => {
		image.src = image_placeholder_path
	})
	clone.querySelectorAll("input[type='text']").forEach(input => {
		input.value = ""
		init_autocomplete(input);
	})
	clone.querySelectorAll("input[type='file']").forEach(input => {
		input.files = (new DataTransfer()).files;
		input.addEventListener('change', handleInputChange);
	})
	
	// The first editable image can follow read-only existing images.
	clone.querySelectorAll("*").forEach(element => {
		["id", "name", "list", "for"].forEach(attribute => {
			const value = element.getAttribute(attribute);
			if (value) element.setAttribute(attribute, value.replace(/itemimage_set-\d+-/g, `itemimage_set-${idx}-`));
		});
	});

	add_image_button.before(clone);
})
