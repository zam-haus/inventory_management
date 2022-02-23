
let camera_modal = document.querySelector("#camera_modal")
let camera_modal_obj = new bootstrap.Modal(document.getElementById('camera_modal'))
let camera_video = document.querySelector("#camera_video");
let camera_present_canvas = document.querySelector("#camera_present_canvas");
let camera_click_button = document.querySelector("#camera_click_photo");
let camera_capture_canvas = document.querySelector("#camera_capture_canvas");
let camera_calling_button = null;
let camera_square_size = 0;

function getIntFromString (s){
	return parseInt(s.replaceAll("[\\D]", ""))
}

function getValFromStyle(style, val){
	return getIntFromString(style.getPropertyValue(val));
}

function getClosest (elem, selector) {
	for ( ; elem && elem !== document; elem = elem.parentNode ) {
		if ( elem.matches( selector ) ) return elem;
	}
	return null;
};

function get_parent_width(element){
	let style = window.getComputedStyle(element.parentNode);//camera_present_canvas.parentNode.clientWidth;
	return (getValFromStyle(style, 'width') - getValFromStyle(style, 'padding-left') - getValFromStyle(style, 'padding-right'));
}

function update_present_canvas_size(){
	let size = get_parent_width(camera_present_canvas);
	camera_present_canvas.width = size;
	camera_present_canvas.height = size;
}

function present_canvas_update(){
	if (camera_present_canvas.width == 0){
		update_present_canvas_size();
	}
	let videoWidth = camera_video.videoWidth;
	let videoHeight = camera_video.videoHeight;
	let x_offset = 0;
	let y_offset = 0;
	let scale = 0;
	if (videoWidth < videoHeight){
		scale = camera_present_canvas.width / videoWidth;
		y_offset = (videoHeight - videoWidth)/2;
	}else{
		scale = camera_present_canvas.width / videoHeight;
		x_offset = (videoWidth - videoHeight)/2;
	}
	camera_present_canvas.getContext('2d').drawImage(camera_video, -x_offset, -y_offset, videoWidth*scale, videoHeight*scale);
	if (camera_video.ended == false){
		//setTimeout(present_canvas_update, 1000/30);
		setTimeout(present_canvas_update, 1000/30);
	}
}

function handleInputChange(event){
	let input = event.target;
	let fieldset = getClosest(input, 'div.itemimage_set_item');
	let image_obj = fieldset.querySelectorAll('img')[0];
	const file = input.files[0];
	if(file){
		const fileReader = new FileReader();
		fileReader.readAsDataURL(file);
		fileReader.addEventListener("load", function(){
			image_obj.src = this.result;
			image_obj.removeAttribute("hidden");
			let size = get_parent_width(image_obj);
			//image_obj.width = size;
			//image_obj.height = size;
		})
	}
}

document.querySelectorAll('input[type="file"]').forEach(input => {
	input.addEventListener('change', handleInputChange)
})

camera_modal.addEventListener('show.bs.modal', async function(event){
	camera_calling_button = event.relatedTarget;
	
	let constraints = {
		audio: false,
		video: {
			facingMode: "environment",
		}
	};
	
	let stream = await navigator.mediaDevices.getUserMedia(constraints);

	let stream_settings = stream.getVideoTracks()[0].getSettings();

	// actual width & height of the camera video
	let stream_width = stream_settings.width;
	let stream_height = stream_settings.height;

	if (stream_width > stream_height){
		camera_square_size = stream_height;
	}else{
		camera_square_size = stream_width;
	}

	camera_video.srcObject = stream;
	camera_video.play();
	
	update_present_canvas_size();
	
	present_canvas_update();
});

camera_modal.addEventListener('hide.bs.modal', function(){
	camera_video.srcObject.getVideoTracks()[0].stop();
});

camera_click_button.addEventListener('click', function() {
	let videoWidth = camera_video.videoWidth;
	let videoHeight = camera_video.videoHeight;
	let x_offset = 0;
	let y_offset = 0;
	if (videoWidth > camera_square_size){
		x_offset = (videoWidth - camera_square_size)/2;
	}
	if (videoHeight > camera_square_size){
		y_offset = (videoHeight - camera_square_size)/2;
	}
	camera_capture_canvas.width = camera_square_size;
	camera_capture_canvas.height = camera_square_size;
	camera_capture_canvas.getContext('2d').drawImage(camera_video, -x_offset, -y_offset, videoWidth, videoHeight);

	let fieldset = getClosest(camera_calling_button, 'div.itemimage_set_item');
	let input_obj = fieldset.querySelectorAll('input[type="file"]')[0];

	camera_capture_canvas.toBlob(function(blob){
		let date = new Date();
		let filename = date.getFullYear().toString() + '-' + (date.getMonth() + 1).toString().padStart(2, '0') + '-' + date.getDate().toString().padStart(2, '0') + '_' + date.getHours().toString().padStart(2, '0') + date.getMinutes().toString().padStart(2, '0') + date.getSeconds().toString().padStart(2, '0') + '.jpg';
		let list = new DataTransfer();
		list.items.add(new File([blob], filename));
		input_obj.files = list.files;
		//fire the event, sothat everyone gets notified about the new image
		input_obj.dispatchEvent(new Event('change'));
	},'image/jpeg', 0.9);

	camera_modal_obj.hide();
});
