let ac_datalist = document.querySelector("#id_itemimage_set-0-description_datalist");
let ac_data = []
let ac_objs = []
if (ac_datalist){
	ac_datalist.querySelectorAll("option").forEach( child => {
		ac_data.push({
			'label': child.value,
		});
	});
}else{
	console.log("using autocomplete data from js-file instead of datalist")
	ac_data = [
		{'label': 'Price label'},
		{'label': 'Packaged'},
		{'label': 'Single item (unpacked)'},
	]
}

function init_autocomplete(input_obj){
	input_obj.removeAttribute('list');
	input_obj.classList.remove('textdatalistinput');
	input_obj.setAttribute('autocomplete', 'off');
	let obj = new Autocomplete(input_obj, {
		data: ac_data,
		threshold: 0,
	})
	ac_objs.push(obj);
};

document.querySelectorAll("input[id$='-description']").forEach( input =>{
	init_autocomplete(input);
})
