let function_button = document.querySelector("#function_button");
let measurement_unit_select = document.querySelector("#id_measurement_unit");

function add_span_to_input(){
	console.log("add_span_to_input called");
	let inputs = document.querySelectorAll('input[id$="-amount"]')
	let temp_el = document.createElement("div");
	for (let i = 0; i < inputs.length; i ++){
		let input = inputs[i];
		let parent = input.parentNode;
		console.log(input);
		console.log(parent.tagName)
		if (parent.tagName == 'DIV' && parent.className.indexOf('input-group') != -1){
			console.log("already added the span. doing not again");
			console.log(parent.className)
			continue;
		}
		parent.removeChild(input);//remove the input field from DOM
		temp_el.innerHTML = '<div class="input-group"><span class="input-group-text amount_print_meas_unit"></span></div>'
		let group = temp_el.firstChild;//get the object from text
		group.prepend(input)//insert the input-tag into the new created element
		parent.appendChild(group);//add the div into DOM
	}
}

function update_measurement_unit_after_amount(){
	value = measurement_unit_select.options[measurement_unit_select.selectedIndex].innerHTML;
	document.querySelectorAll('span.amount_print_meas_unit').forEach(span => {
		span.innerHTML = value;
	})
}

add_span_to_input();

update_measurement_unit_after_amount();

measurement_unit_select.addEventListener('change',  update_measurement_unit_after_amount);
