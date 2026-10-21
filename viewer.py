"""Standalone, offline WebGL point-cloud viewer."""

from pathlib import Path
import base64
import json
import numpy as np


def write_viewer(output, cloud):
    p = cloud["points"]
    c = cloud["colors"]
    count = len(p)
    choose = np.random.default_rng(42).choice(count, min(count, 500000), replace=False)
    center = (p.min(axis=0) + p.max(axis=0)) / 2
    scale = max(float(np.ptp(p, axis=0).max() / 2), 0.01)
    values = np.column_stack(((p[choose] - center) / scale, c[choose] / 255)).astype("<f4")
    encoded = base64.b64encode(values.tobytes()).decode("ascii")
    page = """<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RPBot Map Studio · bản đồ 3D</title>
<style>body{margin:0;background:#142131;color:#edf4fb;font:14px system-ui}canvas{display:block;width:100vw;height:100vh;touch-action:none}aside{position:absolute;left:18px;top:18px;padding:16px;background:#0c1623e8;border:1px solid #304459;border-radius:12px;max-width:360px}h2{font-size:20px;margin:0 0 9px}p{font-size:13px;margin:7px 0}button{padding:7px 12px;cursor:pointer}a{color:#86c6ff}#err{color:#ffb1a3}</style>
<canvas id="map"></canvas><aside><h2>RPBot Map Studio</h2><p>COUNT điểm · Hiển thị SHOW điểm</p><p>Kéo để xoay · Cuộn để zoom · Shift + kéo để di chuyển</p><p>Tọa độ và màu theo dữ liệu đầu vào; xem nguồn và giới hạn trong báo cáo. Không chạy lại SLAM.</p><p><a href="index.html">Báo cáo</a> · <a href="map_3d_cloud.ply">PLY đầy đủ</a></p><button id="reset">Góc nhìn ban đầu</button><p id="err"></p></aside>
<script>
const binary=atob('BLOB'),raw=new Uint8Array(binary.length);for(let i=0;i<binary.length;i++)raw[i]=binary.charCodeAt(i);
const data=new Float32Array(raw.buffer),canvas=document.getElementById('map'),gl=canvas.getContext('webgl',{antialias:true});
if(!gl){document.getElementById('err').textContent='Cần bật WebGL trong trình duyệt để hiển thị 3D.';throw Error('WebGL unavailable')}
function shader(type,src){let s=gl.createShader(type);gl.shaderSource(s,src);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s}
const program=gl.createProgram();gl.attachShader(program,shader(gl.VERTEX_SHADER,`attribute vec3 pos;attribute vec3 color;varying vec3 rgb;uniform float yaw,pitch,zoom,aspect,size;uniform vec2 pan;void main(){float c=cos(yaw),s=sin(yaw),a=cos(pitch),b=sin(pitch);vec3 p=vec3(c*pos.x-s*pos.y,s*pos.x+c*pos.y,pos.z);vec3 q=vec3(p.x,a*p.y-b*p.z,b*p.y+a*p.z);gl_Position=vec4((q.x*zoom+pan.x)/aspect,q.z*zoom+pan.y,q.y*.3,1.);gl_PointSize=size;rgb=color;}`));
gl.attachShader(program,shader(gl.FRAGMENT_SHADER,`precision mediump float;varying vec3 rgb;void main(){gl_FragColor=vec4(rgb,1.);}`));gl.linkProgram(program);gl.useProgram(program);
let buf=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buf);gl.bufferData(gl.ARRAY_BUFFER,data,gl.STATIC_DRAW);
for(const [name,offset] of [['pos',0],['color',12]]){let l=gl.getAttribLocation(program,name);gl.enableVertexAttribArray(l);gl.vertexAttribPointer(l,3,gl.FLOAT,false,24,offset)}
let yaw=-.6,pitch=.9,zoom=.8,pan=[0,0],drag=null;const u={};for(const n of ['yaw','pitch','zoom','aspect','pan','size'])u[n]=gl.getUniformLocation(program,n);
function render(){let d=devicePixelRatio||1;canvas.width=Math.round(innerWidth*d);canvas.height=Math.round(innerHeight*d);gl.viewport(0,0,canvas.width,canvas.height);gl.clearColor(.07,.12,.18,1);gl.enable(gl.DEPTH_TEST);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.uniform1f(u.yaw,yaw);gl.uniform1f(u.pitch,pitch);gl.uniform1f(u.zoom,zoom);gl.uniform1f(u.aspect,innerWidth/innerHeight);gl.uniform1f(u.size,Math.min(3,1.5*d));gl.uniform2fv(u.pan,pan);gl.drawArrays(gl.POINTS,0,data.length/6)}
canvas.onpointerdown=e=>{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId)};canvas.onpointerup=()=>drag=null;
canvas.onpointermove=e=>{if(!drag)return;let dx=e.clientX-drag[0],dy=e.clientY-drag[1];if(e.shiftKey){pan[0]+=dx*2/innerHeight;pan[1]-=dy*2/innerHeight}else{yaw+=dx*.006;pitch=Math.max(-1.55,Math.min(1.55,pitch+dy*.006))}drag=[e.clientX,e.clientY];render()};
canvas.onwheel=e=>{e.preventDefault();zoom=Math.max(.1,Math.min(50,zoom*Math.exp(-e.deltaY*.001)));render()};document.getElementById('reset').onclick=()=>{yaw=-.6;pitch=.9;zoom=.8;pan=[0,0];render()};onresize=render;render();
</script></html>"""
    page = (
        page.replace("COUNT", f"{count:,}")
        .replace("SHOW", f"{len(choose):,}")
        .replace("BLOB", encoded)
    )
    (Path(output) / "view_map_3d.html").write_text(page, encoding="utf-8")
