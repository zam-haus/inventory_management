let add_image_button = document.querySelector('#add_image_button')
let image_count_input = document.querySelector("#id_itemimage_set-TOTAL_FORMS")
let image_placeholder_path = document.querySelector('#placeholder_path').value;

add_image_button.addEventListener('click', function() {
	let idx = image_count_input.value;
	image_count_input.value = idx +1;
	let original = document.querySelectorAll("div.itemimage_set_item")[0]
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
	
	//rename all ids and names
	let elements = [
		["div_id_itemimage_set-", "-description"],
		["itemimage_set-", "-description"],
		["id_itemimage_set-", "-description"],
		["id_itemimage_set-", "-description_datalist"],
		["div_id_itemimage_set-", "-image"],
		["itemimage_set-", "-image"],
		["id_itemimage_set-", "-image"],
	];
	elements.forEach( element => {
		let org_el = element[0] + 0 + element[1]
		let new_el = element[0] + idx + element[1]
		let id = clone.querySelector("#" + org_el);
		if (id){
			id.id = new_el;
		}
		clone.querySelectorAll("[name='" + org_el + "']").forEach(item => {
			item.name = new_el
		});
		clone.querySelectorAll("[list='" + org_el + "']").forEach(item => {
			item.list = new_el
		});
	});
	
	add_image_button.before(clone);
})
