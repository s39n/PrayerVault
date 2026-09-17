"use strict";
// PrayerVault animated veil (WebGL). Progressive enhancement: if WebGL is
// unavailable or the viewer prefers reduced motion, this does nothing and the
// static SVG veils remain the background.
(function () {
  var cv = document.getElementById("veil-gl");
  if (!cv) return;
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  var gl = null;
  try {
    gl = cv.getContext("webgl", { antialias: true, alpha: true, premultipliedAlpha: false })
      || cv.getContext("experimental-webgl", { antialias: true, alpha: true, premultipliedAlpha: false });
  } catch (e) { gl = null; }
  if (!gl) return;

  var VERT = "attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}";
  var FRAG = `precision highp float;
  uniform vec2 u_res; uniform float u_time; uniform float u_cw; uniform float u_wind; uniform float u_ribs;
  float hash(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
  float noise(vec2 p){vec2 i=floor(p),f=fract(p);float a=hash(i),b=hash(i+vec2(1,0)),c=hash(i+vec2(0,1)),d=hash(i+vec2(1,1));vec2 u=f*f*(3.-2.*f);return mix(mix(a,b,u.x),mix(c,d,u.x),u.y);}
  float fbm(vec2 p){float s=0.,a=.5;for(int i=0;i<5;i++){s+=a*noise(p);p*=2.03;a*=.5;}return s;}
  vec4 curtain(float x,float y,float t){
    float w=u_wind;
    float flow=sin(y*0.010 - t*0.6*w)*0.6 + sin(y*0.021 + t*0.35*w)*0.4;
    flow += (fbm(vec2(y*0.02, t*0.12*w))-0.5)*0.5;
    float flowPx=flow*u_cw*0.12;
    float ragged=(fbm(vec2(y*0.004,11.0))-0.5)*u_cw*0.20 + (fbm(vec2(y*0.03,27.0))-0.5)*u_cw*0.05;
    float edge=u_cw*0.80 + ragged + flowPx;
    if(x>edge) return vec4(0.0);
    float u=clamp(x/edge,0.0,1.0);
    float base=u_cw*0.80; float Dedge=ragged+flowPx;
    float wgt=smoothstep(0.0,1.0,u);
    float mx=x - Dedge*wgt;
    float um=clamp(mx/base,0.0,1.0);
    float body=smoothstep(0.0,0.30,um)*smoothstep(1.0,0.72,um);
    float meander=(fbm(vec2(um*2.0,y*0.005))-0.5)*0.5*body;
    float pcoord=pow(um,0.60)*u_ribs + meander;
    float fold=cos(pcoord*6.2831853);
    float grain=(fbm(vec2(um*40.0,y*0.9))-0.5)*0.06;
    float shade=0.5+0.5*fold;
    vec3 sh=vec3(.16,.03,.03),mid=vec3(.36,.09,.09),hi=vec3(.55,.18,.17);
    vec3 col=mix(sh,mid,smoothstep(0.,.6,shade)); col=mix(col,hi,smoothstep(.55,1.,shade));
    col+=grain;
    float sheen=smoothstep(.6,1.,fold)*(0.5+0.5*sin(y*0.004 - t*0.5*w));
    col+=vec3(.14,.05,.05)*sheen;
    col*=mix(.70,1.0,smoothstep(0.,.25,u));
    col*=mix(1.06,.88,y/u_res.y);
    float rim=smoothstep(edge-14.,edge-2.,x); col+=vec3(.35,.24,.08)*rim*.5;
    float cov=1.0;
    if(x>edge-6.4){ float th=noise(vec2(y*3.5+flow*4.0,u*25.0+t*0.08*w));
      float k=(x-(edge-6.4))/6.4; cov=step(k,th*1.1); }
    return vec4(col,cov);
  }
  void main(){
    vec2 fc=gl_FragCoord.xy; float t=u_time;
    vec4 L=curtain(fc.x,fc.y,t);
    vec4 R=curtain(u_res.x-fc.x,fc.y,t+37.0);
    vec4 o = L.a>0.5 ? L : R;
    if(o.a<0.5) discard;
    gl_FragColor=vec4(o.rgb,1.0);
  }`;

  function sh(type, src) {
    var o = gl.createShader(type);
    gl.shaderSource(o, src); gl.compileShader(o);
    if (!gl.getShaderParameter(o, gl.COMPILE_STATUS)) return null;
    return o;
  }
  var vs = sh(gl.VERTEX_SHADER, VERT), fs = sh(gl.FRAGMENT_SHADER, FRAG);
  if (!vs || !fs) return;
  var pr = gl.createProgram();
  gl.attachShader(pr, vs); gl.attachShader(pr, fs); gl.linkProgram(pr);
  if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) return;
  gl.useProgram(pr);
  var b = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, b);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  var l = gl.getAttribLocation(pr, "p");
  gl.enableVertexAttribArray(l); gl.vertexAttribPointer(l, 2, gl.FLOAT, false, 0, 0);
  var uR = gl.getUniformLocation(pr, "u_res"), uT = gl.getUniformLocation(pr, "u_time"),
      uCw = gl.getUniformLocation(pr, "u_cw"), uW = gl.getUniformLocation(pr, "u_wind"),
      uRibs = gl.getUniformLocation(pr, "u_ribs");

  // WebGL is good: reveal the canvas and hide the static SVG veils.
  document.body.classList.add("veil-gl-on");

  var dpr = 1, W = 0, H = 0;
  function rz() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = Math.floor(window.innerWidth * dpr); H = Math.floor(window.innerHeight * dpr);
    cv.width = W; cv.height = H; gl.viewport(0, 0, W, H);
  }
  rz(); window.addEventListener("resize", rz);

  var running = true, raf = 0;
  function frame(ms) {
    if (!running) return;
    var avgW = Math.min(Math.max(window.innerWidth * 0.18, 52), 150); // narrower on desktop, phone unchanged
    var cw = avgW / 0.8 * dpr;
    var ribs = Math.min(Math.max(avgW * 0.121, 7.0), 40.0);           // keep rib thickness ~constant
    gl.uniform2f(uR, W, H); gl.uniform1f(uT, ms * 0.001);
    gl.uniform1f(uCw, cw); gl.uniform1f(uRibs, ribs); gl.uniform1f(uW, 1.0); // medium wind at rest
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    raf = window.requestAnimationFrame(frame);
  }
  raf = window.requestAnimationFrame(frame);

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) { running = false; if (raf) window.cancelAnimationFrame(raf); }
    else if (!running) { running = true; raf = window.requestAnimationFrame(frame); }
  });
})();
