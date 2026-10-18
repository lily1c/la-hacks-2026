const $=id=>document.getElementById(id);const apiBase=location.port==='8792'?'http://127.0.0.1:8790':'';let map,glMod,sim=false,marker,trail=[],tick=0,previous=0,globeProjection=false,imageryEnabled=false;const center=[-118.4452,34.0722];const empty={type:'FeatureCollection',features:[]};
const GLOBE_ENTER_ZOOM=2,GLOBE_EXIT_ZOOM=3;
function updateProjection(){
  if(!map)return;
  const zoom=map.getZoom();
  if(!globeProjection&&zoom<=GLOBE_ENTER_ZOOM){map.setProjection({type:'globe'});globeProjection=true;}
  else if(globeProjection&&zoom>=GLOBE_EXIT_ZOOM){map.setProjection({type:'mercator'});globeProjection=false;}
  $('mapMode').textContent=globeProjection?'Globe view · zoom in for field detail':imageryEnabled?'ArcGIS World Imagery · satellite roofs':sim?'Synthetic fire & flight':'Basemap · No GPS connected';
}
let ws=null,wsConnected=false,wsReconnectTimer=null,prevBlobUrl=null,lastWsTelemetryTime=0,latestTelemetry=null;
const urlParams=new URLSearchParams(location.search);
let beagleHost=urlParams.get('beagle')||localStorage.getItem('firesight_beagle_host')||`${location.hostname||'127.0.0.1'}:8765`;
$('beagleHost').value=beagleHost;

function createDroneMarkerElement(label='Drone'){
  const el=document.createElement('div');
  el.className='drone';
  el.setAttribute('aria-label',label);
  el.innerHTML='<svg class="drone-sketch" viewBox="0 0 48 48" aria-hidden="true"><g fill="#fff8e5" stroke="#3d6452" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 12L36 36M12 36L36 12" fill="none"/><ellipse cx="11" cy="12" rx="8" ry="6.5"/><ellipse cx="37" cy="12" rx="7.5" ry="7"/><ellipse cx="11" cy="36" rx="7.5" ry="7"/><ellipse cx="37" cy="36" rx="8" ry="6.5"/><path d="M20 16Q24 12 28 16L29 29Q24 35 19 29Z" fill="#eea16e"/><path d="M24 7l-3 5h6z" fill="#3d6452"/><path d="M6 12l10-1M32 12l10 1M6 36l10 1M32 36l10-1"/></g></svg>';
  return el;
}

function voToLngLat(x,z){
  // Map local visual odometry X (right/east) and Z (forward/north) meters around UCLA map center
  const scale=4.0;
  const dLng=(Number(x)||0)*scale*0.0000108;
  const dLat=(Number(z)||0)*scale*0.0000090;
  return [center[0]+dLng,center[1]+dLat];
}

let geoTrail=[],geoOriginKey='',geoOrigin=null,originMarker=null;
const geoNote=g=>{const tf=g.transform_v_to_e||{};return `${g.origin?.source||'?'} origin · scale ${tf.scale_status||'?'}${tf.calibrated?'':' (unscaled)'}`;};

// Geo-referenced path: the Beagle Eyes gps_tf transform supplies lat/lon, so no local guessing is needed.
function updateLiveMapFromGeo(t,g){
  const lla=g.drone.lla,lngLat=[lla[1],lla[0]];
  const key=`${g.origin.lat},${g.origin.lon}`;
  if(key!==geoOriginKey){
    geoOriginKey=key;geoTrail=[];geoOrigin=[g.origin.lon,g.origin.lat];
    map.jumpTo({center:geoOrigin,zoom:18});
    originMarker?.remove();
    originMarker=new glMod.Marker({color:'#f0804b'}).setLngLat(geoOrigin).setPopup(new glMod.Popup({offset:24}).setText(`Start / origin (${g.origin.source})`)).addTo(map);
  }
  if(!marker){
    marker=new glMod.Marker({element:createDroneMarkerElement('Beagle Eyes drone')}).setLngLat(lngLat).addTo(map);
  }else{
    marker.setLngLat(lngLat);
  }
  const sketch=marker.getElement().querySelector('.drone-sketch');
  if(sketch&&g.drone.heading_true_deg!=null)sketch.style.transform=`rotate(${g.drone.heading_true_deg}deg)`;
  const last=geoTrail[geoTrail.length-1];
  if(!last||Math.abs(last[0]-lngLat[0])+Math.abs(last[1]-lngLat[1])>1e-7){geoTrail.push(lngLat);if(geoTrail.length>3000)geoTrail.shift();}
  if(geoTrail.length>1&&map.getSource('path'))map.getSource('path').setData({type:'Feature',properties:{},geometry:{type:'LineString',coordinates:geoTrail}});
  const dets=Array.isArray(g.detections)?g.detections:[];
  if(map.getSource('people')){
    map.getSource('people').setData({type:'FeatureCollection',features:dets.filter(d=>Array.isArray(d.lla)).map(d=>({
      type:'Feature',properties:{id:d.id,distance:d.range_m},geometry:{type:'Point',coordinates:[d.lla[1],d.lla[0]]}}))});
  }
  $('mapTitle').textContent='Beagle Eyes / Geo-referenced';
  $('mapMode').textContent=`DPVO ${t.initialized?'Tracking':'Initializing'} · ${geoNote(g)}`;
  const e=g.drone.enu;
  $('mapInfo').textContent=`${lla[0].toFixed(6)}, ${lla[1].toFixed(6)} · ENU ${e.map(v=>v.toFixed(1)).join(', ')}m · AGL ${g.drone.height_agl_m}m · People: ${dets.length}`+(g.transform_v_to_e?.calibrated?'':' · distances unscaled');
}

function updateLiveMapFromTelemetry(t){
  if(sim||!map||!map.isStyleLoaded()||!glMod)return;
  if(t?.geo?.drone?.lla&&t.geo.origin){updateLiveMapFromGeo(t,t.geo);return;}
  const pos=t?.pose?.position;
  if(!Array.isArray(pos)||pos.length<3)return;
  const lngLat=voToLngLat(pos[0],pos[2]);
  if(!marker){
    marker=new glMod.Marker({element:createDroneMarkerElement('Beagle Eyes drone')}).setLngLat(lngLat).addTo(map);
  }else{
    marker.setLngLat(lngLat);
  }
  const q=t.pose?.quaternion;
  if(Array.isArray(q)&&q.length===4){
    const [qx,qy,qz,qw]=q;
    const yaw=Math.atan2(2*(qw*qy+qx*qz),1-2*(qy*qy+qz*qz))*180/Math.PI;
    const sketch=marker.getElement().querySelector('.drone-sketch');
    if(sketch)sketch.style.transform=`rotate(${yaw}deg)`;
  }
  const traj=Array.isArray(t.trajectory)&&t.trajectory.length>1?t.trajectory.map(p=>voToLngLat(p[0],p[2])):[];
  if(traj.length>1&&map.getSource('path')){
    map.getSource('path').setData({type:'Feature',properties:{},geometry:{type:'LineString',coordinates:[...traj,lngLat]}});
  }
  if(map.getSource('people')){
    const dets=Array.isArray(t.detections_3d)?t.detections_3d:[];
    map.getSource('people').setData({
      type:'FeatureCollection',
      features:dets.filter(d=>Array.isArray(d.center)&&d.center.length>=3).map(d=>({
        type:'Feature',
        properties:{id:d.id,distance:d.distance_m},
        geometry:{type:'Point',coordinates:voToLngLat(d.center[0],d.center[2])}
      }))
    });
  }
  const detCount=Array.isArray(t.detections_3d)?t.detections_3d.length:0;
  $('mapTitle').textContent='UCLA / Beagle Eyes Live VO';
  $('mapMode').textContent=`DPVO ${t.initialized?'Tracking':'Initializing'} · Frame #${t.frame_id??0}`;
  $('mapInfo').textContent=`Live VO pose (${pos.map(v=>Number(v).toFixed(2)).join(', ')}m) · People: ${detCount}`;
}

function renderTelemetryUI(t,sourceLabel='Live WS'){
  if(!t)return;
  latestTelemetry=t;
  const xyz=t.pose?.position;
  const enu=t.geo?.drone?.enu;
  $('position').textContent=Array.isArray(enu)&&enu.length===3?`E ${enu[0].toFixed(1)} / N ${enu[1].toFixed(1)} / U ${enu[2].toFixed(1)} m`:Array.isArray(xyz)&&xyz.length===3?xyz.map(v=>(Number(v)>=0?'+':'')+Number(v).toFixed(2)).join(' / ')+' m':'— / — / —';
  const fps=t.fps!=null?Number(t.fps).toFixed(1):'—';
  const voHz=t.vo_hz!=null?Number(t.vo_hz).toFixed(1):fps;
  $('voRate').textContent=`${fps} FPS · ${voHz} Hz`;
  const inferStr=t.infer_ms!=null?` (${Number(t.infer_ms).toFixed(1)}ms)`:'';
  $('voState').textContent=`${t.initialized?'Tracking':'Init'}${inferStr}`;
  const dets=Array.isArray(t.detections_3d)?t.detections_3d:[];
  if(dets.length>0){
    const closest=dets.reduce((a,b)=>(a.distance_m??999)<=(b.distance_m??999)?a:b);
    const gd=Array.isArray(t.geo?.detections)?t.geo.detections.reduce((a,b)=>(a.range_m??999)<=(b.range_m??999)?a:b,{}):{};
    $('peopleCount').textContent=gd.range_m!=null?`${dets.length} (${gd.range_m}m @ ${gd.bearing_true_deg}°)`:`${dets.length} (${Number(closest.distance_m||0).toFixed(1)}m)`;
  }else{
    $('peopleCount').textContent='0 detected';
  }
  $('frameAge').textContent=`${sourceLabel} #${t.frame_id??0}`;
  $('frameSub').textContent=`${fps} FPS · ${t.initialized?'VO locked':'VO init'}`;
  updateLiveMapFromTelemetry(t);
}

function connectBeagleWS(hostInput){
  if(hostInput)beagleHost=hostInput.trim();
  if(!beagleHost)return;
  if(wsReconnectTimer){clearTimeout(wsReconnectTimer);wsReconnectTimer=null;}
  if(ws){try{ws.onclose=null;ws.close();}catch{}ws=null;}
  const isSecure=beagleHost.startsWith('https://')||beagleHost.startsWith('wss://')||beagleHost.includes('trycloudflare.com')||(location.protocol==='https:'&&!beagleHost.includes(':'));
  const cleanHost=beagleHost.replace(/^(https?|wss?):\/\//,'').replace(/\/.*$/,'');
  const wsUrl=`${isSecure?'wss':'ws'}://${cleanHost}/ws`;
  try{
    ws=new WebSocket(wsUrl);
    ws.binaryType='blob';
    ws.onopen=()=>{
      wsConnected=true;
      $('cameraState').textContent='LIVE WS';
      $('cameraState').classList.add('live');
    };
    ws.onclose=()=>{
      wsConnected=false;
      $('cameraState').classList.remove('live');
      wsReconnectTimer=setTimeout(()=>connectBeagleWS(),1500);
    };
    ws.onerror=()=>{try{ws.close();}catch{}};
    ws.onmessage=(ev)=>{
      if(ev.data instanceof Blob){
        const nextUrl=URL.createObjectURL(ev.data);
        $('camera').src=nextUrl;
        $('camera').hidden=false;
        $('cameraEmpty').hidden=true;
        if(prevBlobUrl)URL.revokeObjectURL(prevBlobUrl);
        prevBlobUrl=nextUrl;
        return;
      }
      try{
        const msg=JSON.parse(ev.data);
        if(msg.type==='telemetry'||msg.pose){
          lastWsTelemetryTime=Date.now();
          renderTelemetryUI(msg,'Live WS');
        }
      }catch{}
    };
  }catch{
    wsReconnectTimer=setTimeout(()=>connectBeagleWS(),2000);
  }
}

$('beagleConnect').onclick=()=>{
  const val=$('beagleHost').value.trim();
  if(val){
    localStorage.setItem('firesight_beagle_host',val);
    connectBeagleWS(val);
  }
};
$('beagleHost').addEventListener('keydown',e=>{if(e.key==='Enter')$('beagleConnect').click();});
connectBeagleWS(beagleHost);

$('replay').onclick=()=>{const hidden=document.body.classList.toggle('focus-map');$('replay').textContent=hidden?'Show panels':'Hide panels';};
try{const gl=await import('https://unpkg.com/maplibre-gl@6.14.0/dist/maplibre-gl.mjs');glMod=gl;map=new gl.Map({container:'map',style:'https://tiles.openfreemap.org/styles/liberty',center,zoom:16,pitch:58,bearing:-28});map.setRenderWorldCopies(false);map.addControl(new gl.NavigationControl());map.on('load',()=>{updateProjection();map.on('zoom',updateProjection);const labels=map.getStyle().layers.find(l=>l.type==='symbol')?.id;map.addSource('arcgis-imagery',{type:'raster',tiles:['https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],tileSize:256,attribution:'Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community'});map.addLayer({id:'arcgis-imagery',source:'arcgis-imagery',type:'raster',layout:{visibility:'none'},paint:{'raster-opacity':1}},labels);$('imagery').disabled=false;map.addSource('buildings',{type:'vector',url:'https://tiles.openfreemap.org/planet'});const buildingHeight=['max',['coalesce',['get','render_height'],5],['+', ['coalesce',['get','render_min_height'],0],3]],buildingBase=['coalesce',['get','render_min_height'],0];const buildingColor=illustrated=>illustrated?['case',['has','colour'],['get','colour'],['>',buildingHeight,55],'#434c49',['match',['%', ['id'],4],0,'#d8c3a8',1,'#b9785e',2,'#aaa99c','#ddd0b8']]:['coalesce',['get','colour'],['interpolate',['linear'],['coalesce',['get','render_height'],5],0,'#d4d6d4',12,'#bfc3c2',45,'#a9aead',120,'#8f999d']];map.setLight({anchor:'viewport',color:'#fff8eb',intensity:.42,position:[1.15,210,42]});map.addLayer({id:'buildings',source:'buildings','source-layer':'building',type:'fill-extrusion',filter:['!=',['get','hide_3d'],true],minzoom:14,paint:{'fill-extrusion-color':buildingColor(true),'fill-extrusion-height':buildingHeight,'fill-extrusion-base':buildingBase,'fill-extrusion-opacity':.98,'fill-extrusion-vertical-gradient':true}},labels);map.addLayer({id:'building-edges',source:'buildings','source-layer':'building',type:'line',filter:['!=',['get','hide_3d'],true],minzoom:15,paint:{'line-color':'#59635f','line-width':.45,'line-opacity':.2}},labels);const original=[];let illustrated=true;
for(const l of map.getStyle().layers){let prop,value;if(l.type==='background'){prop='background-color';value='#f3eddb';}else if(l.type==='fill'){prop='fill-color';value=/water/.test(l.id)?'#a9d9df':/park|landcover|landuse|grass|wood/.test(l.id)?'#cee3ad':/building/.test(l.id)?'#eedbc0':null;}else if(l.type==='line'&&/road|transport/.test(l.id)){prop='line-color';value=/motorway|trunk|primary/.test(l.id)?'#e9c48e':'#fffaf0';}if(value){original.push([l.id,prop,map.getPaintProperty(l.id,prop),value]);}}
function applyLook(){for(const [id,prop,before,after] of original)map.setPaintProperty(id,prop,illustrated?after:before);map.setPaintProperty('buildings','fill-extrusion-color',buildingColor(illustrated));map.setPaintProperty('building-edges','line-opacity',illustrated?.16:.24);document.body.classList.toggle('illustrated',illustrated);$('look').textContent=illustrated?'Style: illustrated':'Style: standard';$('look').setAttribute('aria-pressed',String(illustrated));}
$('look').onclick=()=>{illustrated=!illustrated;applyLook();};applyLook();
map.addSource('scenario',{type:'geojson',data:empty});map.addLayer({id:'scenario',source:'scenario',type:'fill',paint:{'fill-color':'#ed6a3b','fill-opacity':.45}});map.addSource('path',{type:'geojson',data:empty});map.addLayer({id:'path',source:'path',type:'line',layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':'#c47d52','line-width':2.5,'line-opacity':.8}});
map.addSource('people',{type:'geojson',data:empty});map.addLayer({id:'people',source:'people',type:'circle',paint:{'circle-radius':6,'circle-color':'#1f2937','circle-stroke-width':2,'circle-stroke-color':'#ffffff'}});
if(latestTelemetry)updateLiveMapFromTelemetry(latestTelemetry);
});
function scenario(){if(!map.isStyleLoaded()){$('mapInfo').textContent='Map still loading; try again shortly.';return;}sim=!sim;trail=[];tick=0;marker?.remove();marker=null;map.getSource('path').setData(empty);$('demo').textContent=sim?'Stop scenario':'Start scenario';$('demo').classList.toggle('active',sim);$('mapTitle').textContent=sim?'Wildfire / Simulation':'UCLA / Field map';$('mapMode').textContent=globeProjection?'Globe view · zoom in for field detail':imageryEnabled?'ArcGIS World Imagery · satellite roofs':sim?'Synthetic fire & flight':'Basemap · No GPS connected';$('mapInfo').textContent=sim?'Orange: invented fire zone · moving icon: simulated drone':'Real map. Awaiting geographic telemetry.';const pts=[[-.0007,-.0003],[-.0005,.0004],[.0001,.0006],[.0006,.0002],[.0004,-.0004],[-.0007,-.0003]].map(p=>[center[0]+p[0],center[1]+p[1]]);map.getSource('scenario').setData(sim?{type:'Feature',properties:{},geometry:{type:'Polygon',coordinates:[pts]}}:empty);if(sim){marker=new gl.Marker({element:createDroneMarkerElement('Simulated drone')}).setLngLat(center).addTo(map);}else if(latestTelemetry){updateLiveMapFromTelemetry(latestTelemetry);}}
$('demo').onclick=scenario;$('tilt').onclick=()=>map.easeTo({pitch:map.getPitch()>20?0:58});$('mapView').onclick=()=>map.flyTo({center:geoOrigin||center,zoom:geoOrigin?18:16,pitch:58,bearing:-28});
function updateMapInfo(){$('mapInfo').textContent=imageryEnabled?'ArcGIS World Imagery · satellite roofs':sim?'Orange: invented fire zone · moving icon: simulated drone':'Real map. Awaiting geographic telemetry.';}
function setImagery(enabled){if(!map?.getLayer('arcgis-imagery'))return;imageryEnabled=enabled;map.setLayoutProperty('arcgis-imagery','visibility',enabled?'visible':'none');map.setLayoutProperty('buildings','visibility',enabled?'none':'visible');map.setLayoutProperty('building-edges','visibility',enabled?'none':'visible');$('imagery').setAttribute('aria-pressed',String(enabled));$('imagery').textContent=enabled?'3D buildings':'Satellite roofs';updateProjection();updateMapInfo();}
$('imagery').onclick=()=>setImagery(!imageryEnabled);
function route(t){return [center[0]+.0013*Math.cos(t)+.00012*Math.sin(3*t),center[1]+.0008*Math.sin(t)+.00008*Math.sin(2*t)];}
function animate(t){const dt=Math.min(Math.max(t-previous,0),50)/1000;previous=t;if(sim&&!document.hidden){tick+=dt;const phase=tick*.12,p=route(phase),ahead=route(phase+.005);marker.setLngLat(p);
// Orient the sketch using projected screen travel, including map bearing/pitch.
const a=map.project(p),b=map.project(ahead),heading=Math.atan2(b.y-a.y,b.x-a.x)*180/Math.PI+90;
marker.getElement().querySelector('.drone-sketch').style.transform=`rotate(${heading}deg)`;
if(!trail.length||Math.hypot(p[0]-trail.at(-1)[0],p[1]-trail.at(-1)[1])>.00001){trail.push(p);trail=trail.slice(-900);}
// Always end the rendered stroke at the current marker position.
const path=[...trail,p];if(path.length>1)map.getSource('path').setData({type:'Feature',properties:{},geometry:{type:'LineString',coordinates:path}});
}requestAnimationFrame(animate);}requestAnimationFrame(animate);
}catch{$('mapInfo').textContent='Map unavailable. Internet access and WebGL required.';}
// G2 card: the phone's live report when there is one, otherwise the recorded demo.
function showG2Live(live){$('g2Video').hidden=live;$('g2Text').hidden=!live;if(live)$('g2Video').pause();else $('g2Video').play().catch(()=>{});}
async function poll(){try{const [liveR,g2R]=await Promise.all([fetch(`${apiBase}/live`,{signal:AbortSignal.timeout(3000)}),fetch(`${apiBase}/g2/status`,{signal:AbortSignal.timeout(3000)})]);if(!liveR.ok||!g2R.ok)throw Error();const live=await liveR.json(),g2=await g2R.json();$('apiStatus').textContent=wsConnected?'Backend + Beagle WS live':'Backend connected';const fresh=live.fresh&&live.snapshot;
if(live.beagle_host&&!urlParams.get('beagle')&&!localStorage.getItem('firesight_beagle_host')&&live.beagle_host!==beagleHost){
  beagleHost=live.beagle_host;$('beagleHost').value=beagleHost;if(!wsConnected)connectBeagleWS(beagleHost);
}
const alertObj=live.snapshot?.alert;
if(alertObj){
  $('hazardState').textContent=alertObj.priority==='critical'?'CRITICAL FIRE':alertObj.priority==='warning'?'WARNING':'Clear';
  $('cameraFoot').textContent=`${alertObj.headline} · ${live.processed||0} analyzed`;
}else{
  $('hazardState').textContent=fresh?'Analyzing...':'Standby';
}
if(!wsConnected){
  $('cameraState').textContent=fresh?'Fresh frame':'Waiting';
  $('camera').hidden=!fresh;
  $('cameraEmpty').hidden=!!fresh;
  if(fresh){
    $('camera').src=live.snapshot.image;
    const telem=live.snapshot.metadata?.telemetry;
    if(telem){
      renderTelemetryUI(telem,'Synced');
    }else{
      const xyz=live.snapshot.metadata?.context?.latest_keyframe_pose?.translation;
      $('position').textContent=xyz?.length===3?xyz.map(v=>Number(v).toFixed(2)).join(' / '):'— / — / —';
      $('frameAge').textContent='Fresh';
    }
  }else if(Date.now()-lastWsTelemetryTime>5000){
    $('position').textContent='— / — / —';
    $('frameAge').textContent='Waiting';
  }
}
const confirmed=g2.fresh&&g2.report?.status==='sdk_accepted';$('g2State').textContent=confirmed?'SDK accepted':'Unconfirmed';$('reportAge').textContent=confirmed?'Fresh report':'Unconfirmed';$('g2Text').textContent=g2.fresh&&g2.report?g2.report.rendered_text||'Display cleared':alertObj?`[Outgoing Alert — ${alertObj.priority.toUpperCase()}]\n${alertObj.headline}\n${(alertObj.instructions||[]).join('\n')}\n\n(Waiting for G2 phone SDK ack)`:'No fresh display report.\n\nWaiting for the phone app.';showG2Live(!!(g2.fresh&&g2.report));$('links').innerHTML=`Beagle WS: <b>${wsConnected?'LIVE ('+beagleHost+')':'reconnecting ('+beagleHost+')'}</b><br>FireSight AI: ${fresh?'analyzing ('+(live.processed||0)+' frames)':live.state||'waiting'} · G2: ${confirmed?'SDK accepted':'unconfirmed'}`;}catch{$('apiStatus').textContent=wsConnected?'Beagle WS live (API offline)':'Backend unavailable';if(!wsConnected){$('camera').hidden=true;$('cameraEmpty').hidden=false;$('cameraState').textContent='Offline';$('position').textContent='— / — / —';$('frameAge').textContent='Unavailable';}$('g2Text').textContent='Backend unavailable. Display state unconfirmed.';showG2Live(false);$('g2State').textContent='Unconfirmed';$('reportAge').textContent='Unconfirmed';$('links').innerHTML=`Beagle WS: <b>${wsConnected?'LIVE ('+beagleHost+')':'offline'}</b><br>Backend API: unavailable`;}setTimeout(poll,2000);}poll();

// ---- Gemini annotations: operator prompt -> map overlays (served by /annotations) ----
// Colour = kind (what it is). Outline/size = severity. Gemini may invent new kinds; each gets a stable colour.
const ANN_PRESETS=[['Car crash','Car crashes or collisions, and the road area they affect'],['Fire & smoke','Visible flames or smoke and the area they cover'],['Blocked road','Roads blocked by vehicles, debris or crowds'],['Vehicles','Every car, truck and bus'],['Trees','Trees and dense vegetation'],['People','People who appear to be in danger or injured'],['People + cars','Mark every person and every car separately']];
const ANN_KIND_COLORS={person:'#e5484d',vehicle:'#3b82f6',tree:'#16a34a',incident:'#f97316',hazard_area:'#a855f7',road_blockage:'#eab308',structure:'#78716c',other:'#06b6d4'};
const ANN_EXTRA_COLORS=['#ec4899','#14b8a6','#84cc16','#f43f5e','#6366f1','#d97706','#0ea5e9','#c026d3'];
const BEAGLE_KEY='__beagle_people',BEAGLE_COLOR='#1f2937';
const annKindColor=k=>ANN_KIND_COLORS[k]||ANN_EXTRA_COLORS[[...k].reduce((h,c)=>(h*31+c.charCodeAt(0))>>>0,7)%ANN_EXTRA_COLORS.length];
const annKindName=k=>k.replace(/_/g,' ');
let annData=null,annLayersReady=false,annHidden=new Set();
try{annHidden=new Set(JSON.parse(localStorage.getItem('ann_hidden')||'[]'));}catch{}
const annSaveHidden=()=>{try{localStorage.setItem('ann_hidden',JSON.stringify([...annHidden]));}catch{}};
function annSetup(){
  const presets=$('annPresets');
  for(const [name,text] of ANN_PRESETS){const b=document.createElement('button');b.type='button';b.textContent=name;b.onclick=()=>{$('annPrompt').value=text;annPush({prompt:text});};presets.append(b);}
  $('annPrompt').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();annRun();}});
  $('annRun').onclick=annRun;
  $('annAuto').onchange=()=>annPush({prompt:$('annPrompt').value,auto:$('annAuto').checked,interval_s:Number($('annInterval').value)});
  $('annInterval').onchange=()=>annPush({interval_s:Number($('annInterval').value)});
  $('annClear').onclick=async()=>{try{annData=await (await fetch(apiBase+'/annotations',{method:'DELETE'})).json();annRender();}catch{}};
}
async function annPush(body){try{const r=await fetch(apiBase+'/annotations/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(r.ok){annData=await r.json();annRender();}}catch{}}
async function annRun(){
  $('annRun').disabled=true;$('annState').textContent='Running';
  try{await annPush({prompt:$('annPrompt').value,auto:$('annAuto').checked,interval_s:Number($('annInterval').value)});const r=await fetch(apiBase+'/annotations/run',{method:'POST'});annData=await r.json();annRender();annFit();}
  catch{$('annStatus').textContent='Annotation service unavailable (needs the FastAPI backend).';$('annStatus').classList.add('err');}
  finally{$('annRun').disabled=false;}
}
function annEnsureLayers(){
  if(annLayersReady||!map||!map.isStyleLoaded())return annLayersReady;
  const empty={type:'FeatureCollection',features:[]};
  const weight=['match',['get','severity'],'critical',4,'warning',3,2];
  map.addSource('ann-areas',{type:'geojson',data:empty});map.addSource('ann-points',{type:'geojson',data:empty});
  map.addLayer({id:'ann-fill',source:'ann-areas',type:'fill',paint:{'fill-color':['get','color'],'fill-opacity':.3}});
  map.addLayer({id:'ann-line',source:'ann-areas',type:'line',paint:{'line-color':['get','color'],'line-width':weight}});
  map.addLayer({id:'ann-pt',source:'ann-points',type:'circle',paint:{'circle-radius':['match',['get','severity'],'critical',11,'warning',9,8],'circle-color':['get','color'],'circle-stroke-color':'#ffffff','circle-stroke-width':2}});
  for(const layer of ['ann-fill','ann-pt'])map.on('click',layer,e=>{const p=e.features[0].properties;new glMod.Popup().setLngLat(e.lngLat).setText(`${p.label} · ${annKindName(p.kind)} · ${p.severity}${p.summary?' — '+p.summary:''}`).addTo(map);});
  return annLayersReady=true;
}
function annVisible(){return (annData?.annotations||[]).filter(a=>a.geometry&&!annHidden.has(a.kind));}
function annDraw(){
  if(map?.getLayer('people'))map.setLayoutProperty('people','visibility',annHidden.has(BEAGLE_KEY)?'none':'visible');
  if(!annEnsureLayers())return;
  const areas=[],points=[];
  for(const a of annVisible()){
    const props={id:a.id,label:a.label,summary:a.summary,severity:a.severity,kind:a.kind,color:annKindColor(a.kind)};
    const ring=a.geometry.latlon.map(([lat,lon])=>[lon,lat]);
    if(a.geometry.type==='Polygon')areas.push({type:'Feature',properties:props,geometry:{type:'Polygon',coordinates:[[...ring,ring[0]]]}});
    else points.push({type:'Feature',properties:props,geometry:{type:'Point',coordinates:ring[0]}});
  }
  map.getSource('ann-areas').setData({type:'FeatureCollection',features:areas});
  map.getSource('ann-points').setData({type:'FeatureCollection',features:points});
}
function annFit(){
  const pts=annVisible().flatMap(a=>a.geometry.latlon.map(([lat,lon])=>[lon,lat]));
  if(!pts.length||!map)return;
  const lons=pts.map(p=>p[0]),lats=pts.map(p=>p[1]);
  map.fitBounds([[Math.min(...lons),Math.min(...lats)],[Math.max(...lons),Math.max(...lats)]],{padding:120,maxZoom:19,duration:600});
}
// Legend: one row per kind on the map (colour swatch, name, count, show/hide), plus Beagle Eyes' own people markers.
function annLegend(list){
  const counts={};for(const a of list)counts[a.kind]=(counts[a.kind]||0)+1;
  const beagle=latestTelemetry?.geo?.detections?.length??latestTelemetry?.detections_3d?.length??0;
  const rows=[...Object.keys(counts).sort().map(k=>({key:k,name:annKindName(k),color:annKindColor(k),count:counts[k]}))];
  if(beagle||annHidden.has(BEAGLE_KEY))rows.push({key:BEAGLE_KEY,name:'people (Beagle VO)',color:BEAGLE_COLOR,count:beagle});
  const box=$('annLayers'),sig=rows.map(r=>`${r.key}:${r.count}:${annHidden.has(r.key)}`).join('|');
  if(box.dataset.sig===sig)return;
  box.dataset.sig=sig;box.replaceChildren();
  if(!rows.length)return;
  for(const r of rows){
    const label=document.createElement('label'),check=document.createElement('input'),swatch=document.createElement('i'),name=document.createElement('span'),count=document.createElement('b');
    check.type='checkbox';check.checked=!annHidden.has(r.key);
    check.onchange=()=>{check.checked?annHidden.delete(r.key):annHidden.add(r.key);annSaveHidden();annDraw();annLegend(annData?.annotations||[]);};
    swatch.className='swatch';swatch.style.background=r.color;name.textContent=r.name;count.textContent=r.count;
    label.className=check.checked?'':'off';label.append(check,swatch,name,count);box.append(label);
  }
  const note=document.createElement('small');note.textContent='Colour = type · outline/size = severity';box.append(note);
}
function annRender(){
  if(!annData)return;
  const d=annData,list=d.annotations||[];
  $('annState').textContent=d.busy?'Running':d.auto?'Auto':'Idle';
  $('annState').classList.toggle('live',d.busy||d.auto);
  if(document.activeElement!==$('annPrompt')&&$('annPrompt').value!==d.prompt)$('annPrompt').value=d.prompt;
  $('annAuto').checked=d.auto;
  const status=$('annStatus');status.classList.toggle('err',!!d.error);
  const placed=list.filter(a=>a.geometry),edge=placed.filter(a=>a.clamped).length;
  status.textContent=d.error?d.error:d.runs?`${list.length} annotation${list.length===1?'':'s'} (${placed.length} on map${edge?`, ${edge} at edge of view`:''}) · ${d.latency_ms} ms · ${d.model}${list.some(a=>a.approx)?' · approximate (unscaled)':''}`:'Type an instruction, then press Annotate now.';
  annLegend(list);
  $('annList').replaceChildren(...list.filter(a=>!annHidden.has(a.kind)).map(a=>{
    const li=document.createElement('li'),dot=document.createElement('span'),text=document.createElement('div');
    dot.className='dot';dot.style.background=annKindColor(a.kind);
    text.textContent=a.label;const sub=document.createElement('small');
    sub.textContent=a.geometry?`${annKindName(a.kind)} · ${a.severity}${a.range_m!=null?` · ${a.range_m} m`:''}${a.clamped?' · edge of view':''}${a.summary?' · '+a.summary:''}`:`${annKindName(a.kind)} · not placed (needs --gps-tf)`;
    text.append(sub);li.append(dot,text);
    li.onclick=()=>{if(!a.geometry||!map)return;const [lat,lon]=a.geometry.latlon[0];map.flyTo({center:[lon,lat],zoom:19});};
    return li;}));
  annDraw();
}
async function annPoll(){try{const r=await fetch(apiBase+'/annotations',{cache:'no-store',signal:AbortSignal.timeout(4000)});if(r.ok){annData=await r.json();annRender();}else if(r.status===404){$('annStatus').textContent='Annotations need the FastAPI backend (pip install -e .).';}}catch{}setTimeout(annPoll,1500);}
annSetup();annPoll();

// ---- G2 wearer: phone GPS reported by the glasses app (served by /wearer) ----
const wearerMarkers=new Map();let wearerCentered=false;
function wearerElement(id){const el=document.createElement('div');el.className='wearer-marker';el.title=`G2 wearer · ${id}`;el.innerHTML='<span></span><b>G2</b>';return el;}
async function wearerPoll(){try{const r=await fetch(apiBase+'/wearer',{cache:'no-store',signal:AbortSignal.timeout(4000)});if(r.ok&&map&&glMod){const {wearers}=await r.json();const seen=new Set();
for(const w of wearers){seen.add(w.device_id);const at=[w.lon,w.lat];let m=wearerMarkers.get(w.device_id);if(!m){m=new glMod.Marker({element:wearerElement(w.device_id)}).setLngLat(at).addTo(map);wearerMarkers.set(w.device_id,m);}else m.setLngLat(at);
if(!wearerCentered){wearerCentered=true;map.easeTo({center:at});}}
for(const [id,m] of wearerMarkers)if(!seen.has(id)){m.remove();wearerMarkers.delete(id);}}}catch{}finally{setTimeout(wearerPoll,2000);}}
wearerPoll();
