
let barcode_modal = document.querySelector("#barcode_modal")
let barcode_modal_obj = new bootstrap.Modal(barcode_modal)
let barcode_textarea = document.querySelector("#id_barcode_data")
let barcode_use_selected_button = document.querySelector("#barcode_use_selected")
let barcode_result_thumbnails = document.querySelector("#result_strip_thumbnails");

if (barcode_textarea){
	let button = document.createElement("button");
	button.setAttribute('type', 'button');
	button.setAttribute('class', 'btn btn-primary');
	button.setAttribute('data-bs-toggle', 'modal');
	button.setAttribute('data-bs-target', '#barcode_modal');
	button.innerHTML = "Start Barcode Scanner";
	barcode_textarea.after(button);
}

barcode_modal.addEventListener('show.bs.modal', async function(event){
	barcode_result_thumbnails.innerHTML = ""
	let options = {
		inputStream: {
			type : "LiveStream",
			target: "#quagga_display",
			constraints: {
				width: {min: 640},
				height: {min: 480},
				facingMode: "environment",
				aspectRatio: {min: 1, max: 2}
			}
		},
		locator: {
			patchSize: "medium",
			halfSample: false,
		},
		numOfWorkers: 4,
		frequency: 10,
		decoder: {
			readers : [{
				format: "ean_reader",
				config: {}
			}],
		},
		locate: true,
	};
	Quagga.init(options, function(err){
		if(err){
			console.log(err);
			return;
		}
		console.log("quagga initialization finished, ready to start");
		Quagga.start();
	});
});

barcode_modal.addEventListener('hide.bs.modal', function(){
	Quagga.stop();
});

barcode_use_selected_button.addEventListener('click', function() {
	let currentval = barcode_textarea.value;
	let children = barcode_result_thumbnails.children
	for (let i = 0; i < children.length; i++){
		let child = children[i];
		let checkbox = child.querySelectorAll("input[type='checkbox']")[0];
		if (checkbox.checked){
			let code = child.querySelectorAll(".code")[0].innerHTML;
			let type = child.querySelectorAll("input[type='text']")[0].value;
			currentval += code + " " + type + "\n";
		}
	}
	barcode_textarea.value = currentval;
	barcode_modal_obj.hide();
});

Quagga.onProcessed(function(result) {
	let drawingCtx = Quagga.canvas.ctx.overlay;
	let drawingCanvas = Quagga.canvas.dom.overlay;

	if (result) {
		if (result.boxes) {
			drawingCtx.clearRect(0, 0, parseInt(drawingCanvas.getAttribute("width")), parseInt(drawingCanvas.getAttribute("height")));
			result.boxes.filter(function (box) {
				return box !== result.box;
			}).forEach(function (box) {
				Quagga.ImageDebug.drawPath(box, {x: 0, y: 1}, drawingCtx, {color: "green", lineWidth: 2});
			});
		}

		if (result.box) {
			Quagga.ImageDebug.drawPath(result.box, {x: 0, y: 1}, drawingCtx, {color: "#00F", lineWidth: 2});
		}

		if (result.codeResult && result.codeResult.code) {
			Quagga.ImageDebug.drawPath(result.line, {x: 'x', y: 'y'}, drawingCtx, {color: 'red', lineWidth: 3});
		}
	}
});

let bscanner_last_result = "";

Quagga.onDetected(function(result) {
	var code = result.codeResult.code;
	
	console.log(result);

	if (bscanner_last_result !== code) {
		bscanner_last_result = code;
		let canvas = Quagga.canvas.dom.image;
		let temp_el = document.createElement("div");
		
		temp_el.innerHTML = '<li><div class="thumbnail"><div class="imgWrapper"><img src="' + canvas.toDataURL() + '"/></div><div class="caption"><div class="code">' + code + '</div><input type="checkbox" class="form-check-input" checked><input type="text" value="' + result.codeResult.format + '" hidden></div></div></li>';
		barcode_result_thumbnails.prepend(temp_el.firstChild);
	}
});
