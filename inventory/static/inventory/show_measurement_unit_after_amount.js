let function_button = document.querySelector("#function_button");
let measurement_unit_select = document.querySelector("#id_measurement_unit");

function update_measurement_unit_after_amount(){
	value = measurement_unit_select.options[measurement_unit_select.selectedIndex].innerHTML;
	document.querySelectorAll('span.amount_print_meas_unit').forEach(span => {
		span.innerHTML = value;
	})
}

update_measurement_unit_after_amount();

measurement_unit_select.addEventListener('change',  update_measurement_unit_after_amount);
