
const $=id=>document.getElementById(id);const apiBase=location.port==='8792'?'http://127.0.0.1:8790':'';let map,glMod,sim=false,marker,trail=[],tick=0,previous=0;const center=[-118.4452,34.0722];const empty={type:'FeatureCollection',features:[]};
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

function updateLiveMapFromTelemetry(t){
  if(sim||!map||!map.isStyleLoaded()||!glMod)return;
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
  $('position').textContent=Array.isArray(xyz)&&xyz.length===3?xyz.map(v=>(Number(v)>=0?'+':'')+Number(v).toFixed(2)).join(' / ')+' m':'— / — / —';
  const fps=t.fps!=null?Number(t.fps).toFixed(1):'—';
  const voHz=t.vo_hz!=null?Number(t.vo_hz).toFixed(1):fps;
  $('voRate').textContent=`${fps} FPS · ${voHz} Hz`;
  const inferStr=t.infer_ms!=null?` (${Number(t.infer_ms).toFixed(1)}ms)`:'';
  $('voState').textContent=`${t.initialized?'Tracking':'Init'}${inferStr}`;
  const dets=Array.isArray(t.detections_3d)?t.detections_3d:[];
  if(dets.length>0){
    const closest=dets.reduce((a,b)=>(a.distance_m??999)<=(b.distance_m??999)?a:b);
    $('peopleCount').textContent=`${dets.length} (${Number(closest.distance_m||0).toFixed(1)}m)`;
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
try{const gl=await import('https://unpkg.com/maplibre-gl@6.14.0/dist/maplibre-gl.mjs');glMod=gl;map=new gl.Map({container:'map',style:'https://tiles.openfreemap.org/styles/liberty',center,zoom:16,pitch:58,bearing:-28});map.addControl(new gl.NavigationControl());map.on('load',()=>{const labels=map.getStyle().layers.find(l=>l.type==='symbol')?.id;map.addSource('buildings',{type:'vector',url:'https://tiles.openfreemap.org/planet'});map.addLayer({id:'buildings',source:'buildings','source-layer':'building',type:'fill-extrusion',minzoom:14,paint:{'fill-extrusion-color':'#b7bba9','fill-extrusion-height':['coalesce',['get','render_height'],3],'fill-extrusion-base':['coalesce',['get','render_min_height'],0]}},labels);const original=[];let illustrated=true;
for(const l of map.getStyle().layers){let prop,value;if(l.type==='background'){prop='background-color';value='#f3eddb';}else if(l.type==='fill'){prop='fill-color';value=/water/.test(l.id)?'#a9d9df':/park|landcover|landuse|grass|wood/.test(l.id)?'#cee3ad':/building/.test(l.id)?'#eedbc0':null;}else if(l.type==='line'&&/road|transport/.test(l.id)){prop='line-color';value=/motorway|trunk|primary/.test(l.id)?'#e9c48e':'#fffaf0';}if(value){original.push([l.id,prop,map.getPaintProperty(l.id,prop),value]);}}
function applyLook(){for(const [id,prop,before,after] of original)map.setPaintProperty(id,prop,illustrated?after:before);map.setPaintProperty('buildings','fill-extrusion-color',illustrated?['interpolate',['linear'],['coalesce',['get','render_height'],3],0,'#f4e3c8',25,'#dbc9aa',70,'#b7cbbb']:'#b7bba9');document.body.classList.toggle('illustrated',illustrated);$('look').textContent=illustrated?'Style: illustrated':'Style: standard';$('look').setAttribute('aria-pressed',String(illustrated));}
$('look').onclick=()=>{illustrated=!illustrated;applyLook();};applyLook();
map.addSource('scenario',{type:'geojson',data:empty});map.addLayer({id:'scenario',source:'scenario',type:'fill',paint:{'fill-color':'#ed6a3b','fill-opacity':.45}});map.addSource('path',{type:'geojson',data:empty});map.addLayer({id:'path',source:'path',type:'line',layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':'#c47d52','line-width':2.5,'line-opacity':.8}});
map.addSource('people',{type:'geojson',data:empty});map.addLayer({id:'people',source:'people',type:'circle',paint:{'circle-radius':6,'circle-color':'#22c55e','circle-stroke-width':2,'circle-stroke-color':'#ffffff'}});
if(latestTelemetry)updateLiveMapFromTelemetry(latestTelemetry);
});
function scenario(){if(!map.isStyleLoaded()){$('mapInfo').textContent='Map still loading; try again shortly.';return;}sim=!sim;trail=[];tick=0;marker?.remove();marker=null;map.getSource('path').setData(empty);$('demo').textContent=sim?'Stop scenario':'Start scenario';$('demo').classList.toggle('active',sim);$('mapTitle').textContent=sim?'Wildfire / Simulation':'UCLA / Field map';$('mapMode').textContent=sim?'Synthetic fire & flight':'Basemap · No GPS connected';$('mapInfo').textContent=sim?'Orange: invented fire zone · moving icon: simulated drone':'Real map. Awaiting geographic telemetry.';const pts=[[-.0007,-.0003],[-.0005,.0004],[.0001,.0006],[.0006,.0002],[.0004,-.0004],[-.0007,-.0003]].map(p=>[center[0]+p[0],center[1]+p[1]]);map.getSource('scenario').setData(sim?{type:'Feature',properties:{},geometry:{type:'Polygon',coordinates:[pts]}}:empty);if(sim){marker=new gl.Marker({element:createDroneMarkerElement('Simulated drone')}).setLngLat(center).addTo(map);}else if(latestTelemetry){updateLiveMapFromTelemetry(latestTelemetry);}}
$('demo').onclick=scenario;$('tilt').onclick=()=>map.easeTo({pitch:map.getPitch()>20?0:58});$('mapView').onclick=()=>map.flyTo({center,zoom:16,pitch:58,bearing:-28});
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
const confirmed=g2.fresh&&g2.report?.status==='sdk_accepted';$('g2State').textContent=confirmed?'SDK accepted':'Unconfirmed';$('reportAge').textContent=confirmed?'Fresh report':'Unconfirmed';$('g2Text').textContent=g2.fresh&&g2.report?g2.report.rendered_text||'Display cleared':alertObj?`[Outgoing Alert — ${alertObj.priority.toUpperCase()}]\n${alertObj.headline}\n${(alertObj.instructions||[]).join('\n')}\n\n(Waiting for G2 phone SDK ack)`:'No fresh display report.\n\nWaiting for the phone app.';$('links').innerHTML=`Beagle WS: <b>${wsConnected?'LIVE ('+beagleHost+')':'reconnecting ('+beagleHost+')'}</b><br>FireSight AI: ${fresh?'analyzing ('+(live.processed||0)+' frames)':live.state||'waiting'} · G2: ${confirmed?'SDK accepted':'unconfirmed'}`;}catch{$('apiStatus').textContent=wsConnected?'Beagle WS live (API offline)':'Backend unavailable';if(!wsConnected){$('camera').hidden=true;$('cameraEmpty').hidden=false;$('cameraState').textContent='Offline';$('position').textContent='— / — / —';$('frameAge').textContent='Unavailable';}$('g2Text').textContent='Backend unavailable. Display state unconfirmed.';$('g2State').textContent='Unconfirmed';$('reportAge').textContent='Unconfirmed';$('links').innerHTML=`Beagle WS: <b>${wsConnected?'LIVE ('+beagleHost+')':'offline'}</b><br>Backend API: unavailable`;}setTimeout(poll,2000);}poll();
