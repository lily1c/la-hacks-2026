'use strict';
const $=id=>document.getElementById(id);
let stream=null,watch=null,active=false,generation=0,request=null,timer=null,fix=null,session=null,frame=0,sent=0;
function stop(message='Stopped. Camera and GPS are off.'){
 active=false;generation++;clearTimeout(timer);request?.abort();request=null;
 stream?.getTracks().forEach(t=>t.stop());stream=null;$('video').srcObject=null;
 if(watch!==null)navigator.geolocation.clearWatch(watch);watch=null;fix=null;
 $('start').disabled=false;$('stop').disabled=true;$('token').disabled=false;$('gps').disabled=false;
 $('status').textContent=message;$('location').textContent='GPS off';
}
async function upload(epoch){
 if(!active||epoch!==generation)return;
 const video=$('video'),canvas=$('canvas');
 try{
  if(!video.videoWidth)throw Error('Waiting for camera');
  const scale=Math.min(1,960/video.videoWidth);canvas.width=Math.round(video.videoWidth*scale);canvas.height=Math.round(video.videoHeight*scale);
  canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);
  const captured=Date.now();const jpeg=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',.75));
  if(!jpeg)throw Error('Camera encoding failed');
  const bytes=new Uint8Array(await jpeg.arrayBuffer());
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
  let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
  const telemetry={type:'telemetry',source:'phone',frame_id:frame++,timestamp:captured/1000,initialized:false};
  if(fix&&captured-fix.timestamp>=0&&captured-fix.timestamp<15000)telemetry.gps={...fix};
  if(!active||epoch!==generation)return;
  request=new AbortController();const timeout=setTimeout(()=>request?.abort(),15000);
  let response;try{response=await fetch('/ingest/beagle',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+$('token').value.trim()},body:JSON.stringify({session_id:session,telemetry,jpeg_base64:btoa(binary),sha256:hash}),signal:request.signal});}finally{clearTimeout(timeout);}
  if(!active||epoch!==generation)return;
  if(response.status===401){stop('Token rejected. Enter the Render INGEST_TOKEN and try again.');return;}
  if(response.status===503){stop('Receiver needs INGEST_MODE=push.');return;}
  if(!response.ok)throw Error('Upload failed (HTTP '+response.status+')');
  const result=await response.json();if(result.accepted)sent++;
  $('status').textContent=`Sending · ${sent} snapshots accepted · ${telemetry.gps?'GPS included':'no fresh GPS'} · ${new Date().toLocaleTimeString()}`;
 }catch(error){if(active&&epoch===generation)$('status').textContent=error.name==='AbortError'?'Upload timed out; retrying…':error.message+'; retrying…';}
 if(active&&epoch===generation)timer=setTimeout(()=>upload(epoch),1000);
}
$('start').onclick=async()=>{
 if(!$('token').value.trim()){$('status').textContent='Enter your ingest token first.';return;}
 if(!navigator.mediaDevices?.getUserMedia){$('status').textContent='Camera requires HTTPS and a supported browser.';return;}
 $('start').disabled=true;const epoch=++generation;active=true;$('stop').disabled=false;$('token').disabled=true;$('gps').disabled=true;
 try{
  const camera=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'},width:{ideal:1280}},audio:false});
  if(!active||epoch!==generation){camera.getTracks().forEach(t=>t.stop());return;}
  stream=camera;$('video').srcObject=stream;await $('video').play();
  if(!active||epoch!==generation)return;
  session=crypto.randomUUID();frame=0;sent=0;
  if($('gps').checked&&navigator.geolocation){
   $('location').textContent='Waiting for GPS permission/fix…';
   watch=navigator.geolocation.watchPosition(p=>{if(!active||epoch!==generation)return;fix={latitude:p.coords.latitude,longitude:p.coords.longitude,accuracy:p.coords.accuracy,altitude:p.coords.altitude,heading:p.coords.heading,timestamp:p.timestamp};$('location').textContent=`GPS accuracy: ±${Math.round(p.coords.accuracy)} m`;},()=>{fix=null;$('location').textContent='GPS unavailable; continuing camera only.';},{enableHighAccuracy:true,maximumAge:5000,timeout:10000});
  }
  upload(epoch);
 }catch(error){if(epoch===generation)stop('Could not start camera: '+error.message);}
};
$('stop').onclick=()=>stop();
window.addEventListener('pagehide',()=>stop());
document.addEventListener('visibilitychange',()=>{if(document.hidden&&active)stop('Paused because the page was hidden. Tap Start to resume.');});
