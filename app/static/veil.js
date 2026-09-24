"use strict";
// PrayerVault animated veil (WebGL, no library). A velvet photo (CC0, Poly Haven
// "Velour Velvet") is baked once into a curtain image with folds, lighting and a
// torn edge, then drawn on a subdivided mesh whose vertices sway with the flow.
// Progressive enhancement: without WebGL, or with reduced motion, nothing runs
// and the static SVG veils stay.
(function () {
  var cv = document.getElementById("veil-gl");
  if (!cv) return;
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  var gl = null;
  try { gl = cv.getContext("webgl", { antialias: true, alpha: true, premultipliedAlpha: true }); } catch (e) { gl = null; }
  if (!gl) return;
  var SRC = window.VEIL_TEX || { diff: "/veil-velvet-diff.jpg", nor: "/veil-velvet-nor.jpg" };

  // ---- 1D noise shared by the bake (JS) and the sway (GLSL) ----
  function h1(i) { var s = Math.sin(i * 127.1 + 311.7) * 43758.5453; return s - Math.floor(s); }
  function n1(x) { var i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f); return h1(i) * (1 - u) + h1(i + 1) * u; }
  function fbm1(x) { var s = 0, a = 0.5; for (var k = 0; k < 5; k++) { s += a * n1(x); x *= 2.03; a *= 0.5; } return s; }
  function sstep(a, b, x) { var t = Math.min(Math.max((x - a) / (b - a), 0), 1); return t * t * (3 - 2 * t); }

  var TW = 512, TH = 1024, EDGE = 0.84, S = TW / 384;   // S keeps proportions of the tuned 384px bake

  // ---- bake the curtain (hung edge at x=0, torn edge toward x=TW) ----
  function bake(diff, nor, ribs, yScale) {
    var c = document.createElement("canvas"); c.width = TW; c.height = TH;
    var ctx = c.getContext("2d"), out = ctx.createImageData(TW, TH), o = out.data;
    var tile = 420 * S, dw = diff.width, dh = diff.height, dd = diff.data, nd = nor.data;
    var L = Math.hypot(0.45, 0.5, 0.75);
    for (var y = 0; y < TH; y++) {
      var ys = y * yScale;
      var rag = (fbm1(ys * 0.004 + 11) - 0.5) * 0.20 + (fbm1(ys * 0.03 + 27) - 0.5) * 0.05;
      var edgeX = TW * (EDGE + rag * EDGE / 0.8), Dedge = edgeX - TW * EDGE, vfall = 1.06 - 0.20 * (y / TH);
      var fray = 6 * S;
      for (var x = 0; x < TW; x++) {
        var i = (y * TW + x) * 4;
        if (x > edgeX) { o[i + 3] = 0; continue; }
        var u = x / edgeX, wgt = sstep(0, 1, u), mx = x - Dedge * wgt, um = Math.min(Math.max(mx / (TW * EDGE), 0), 1);
        var body = sstep(0, 0.30, um) * (1 - sstep(0.72, 1, um));
        var meander = (fbm1(um * 2.0 + ys * 0.0155) - 0.5) * 0.5 * body;
        var ph = (Math.pow(um, 0.6) * ribs + meander) * Math.PI * 2, fold = Math.cos(ph);
        var tx = ((((mx / tile) * dw) % dw) + dw) % dw | 0, ty = ((y / tile) * dh) % dh | 0, ti = (ty * dw + tx) * 4;
        var Nx = -Math.sin(ph) * 0.95 + (nd[ti] / 255 * 2 - 1) * 0.35, Ny = (nd[ti + 1] / 255 * 2 - 1) * 0.35, Nz = 1;
        var nl = Math.hypot(Nx, Ny, Nz); Nx /= nl; Ny /= nl; Nz /= nl;
        var lam = Math.max(-0.45 * Nx + 0.5 * Ny + 0.75 * Nz, 0) / L;
        var k = (0.16 + 1.05 * lam) * (0.42 + 0.58 * (0.5 + 0.5 * fold)), graz = Math.pow(1 - Nz, 2);
        var occ = (0.70 + 0.30 * sstep(0, 0.25, u)) * vfall, rim = sstep(edgeX - 14 * S, edgeX - 2 * S, x) * 0.45;
        var r = (dd[ti] / 255 * 0.78 * k + 0.30 * graz) * occ + 0.30 * rim;
        var g = (dd[ti + 1] / 255 * 0.62 * k + 0.09 * graz) * occ + 0.20 * rim;
        var b = (dd[ti + 2] / 255 * 0.46 * k + 0.10 * graz) * occ + 0.07 * rim;
        var a = 255;
        if (x > edgeX - fray && (x - (edgeX - fray)) / fray > h1(y * 3.7 + (x / S) * 0.31) * 1.1) a = 0;
        o[i] = Math.min(r, 1) * 255; o[i + 1] = Math.min(g, 1) * 255; o[i + 2] = Math.min(b, 1) * 255; o[i + 3] = a;
      }
    }
    ctx.putImageData(out, 0, 0);
    return c;
  }

  // ---- GL: one textured grid mesh, drawn twice (left, mirrored right) ----
  var VS = [
    "attribute vec2 a_uv;",
    "uniform vec2 u_res; uniform float u_time, u_side, u_meshW, u_meshH, u_top, u_amp;",
    "varying vec2 v_uv;",
    "float h1(float i){ return fract(sin(i*127.1+311.7)*43758.5453); }",
    "float n1(float x){ float i=floor(x), f=fract(x); float u=f*f*(3.-2.*f); return mix(h1(i),h1(i+1.),u); }",
    "float fbm1(float x){ float s=0.,a=.5; for(int k=0;k<5;k++){ s+=a*n1(x); x*=2.03; a*=.5; } return s; }",
    "void main(){",
    "  float ys = a_uv.y*u_meshH;",
    "  float flow = sin(ys*0.010-u_time*0.6)*0.6 + sin(ys*0.021+u_time*0.35)*0.4 + (fbm1(ys*0.02+u_time*0.9)-0.5)*0.5;",
    "  float x = a_uv.x*u_meshW + flow*pow(a_uv.x,1.5)*u_amp;",
    "  float y = u_top + ys;",
    "  if (u_side > 0.5) x = u_res.x - x;",
    "  gl_Position = vec4(x/u_res.x*2.-1., 1.-y/u_res.y*2., 0., 1.);",
    "  v_uv = a_uv;",
    "}"].join("\n");
  var FS = "precision mediump float; uniform sampler2D u_tex; varying vec2 v_uv;" +
           "void main(){ vec4 c = texture2D(u_tex, v_uv); if (c.a < 0.004) discard; gl_FragColor = c; }";

  function sh(type, src) { var o = gl.createShader(type); gl.shaderSource(o, src); gl.compileShader(o);
    return gl.getShaderParameter(o, gl.COMPILE_STATUS) ? o : null; }
  var vs = sh(gl.VERTEX_SHADER, VS), fs = sh(gl.FRAGMENT_SHADER, FS);
  if (!vs || !fs) return;
  var pr = gl.createProgram(); gl.attachShader(pr, vs); gl.attachShader(pr, fs); gl.linkProgram(pr);
  if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) return;
  gl.useProgram(pr);

  var VX = 24, VY = 96, uv = new Float32Array(VX * VY * 2), idx = new Uint16Array((VX - 1) * (VY - 1) * 6), n = 0;
  for (var j = 0; j < VY; j++) for (var i = 0; i < VX; i++) { uv[(j * VX + i) * 2] = i / (VX - 1); uv[(j * VX + i) * 2 + 1] = j / (VY - 1); }
  for (j = 0; j < VY - 1; j++) for (i = 0; i < VX - 1; i++) {
    var a = j * VX + i, b = a + 1, c = a + VX, d = c + 1;
    idx[n++] = a; idx[n++] = c; idx[n++] = b; idx[n++] = b; idx[n++] = c; idx[n++] = d;
  }
  var vb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, vb); gl.bufferData(gl.ARRAY_BUFFER, uv, gl.STATIC_DRAW);
  var ib = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, idx, gl.STATIC_DRAW);
  var aUv = gl.getAttribLocation(pr, "a_uv"); gl.enableVertexAttribArray(aUv); gl.vertexAttribPointer(aUv, 2, gl.FLOAT, false, 0, 0);
  function U(nm) { return gl.getUniformLocation(pr, nm); }
  var uRes = U("u_res"), uTime = U("u_time"), uSide = U("u_side"), uMW = U("u_meshW"), uMH = U("u_meshH"), uTop = U("u_top"), uAmp = U("u_amp");
  gl.uniform1i(U("u_tex"), 0);
  gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);   // premultiplied: no dark fringe at the tear
  var tex = gl.createTexture();

  function loadImg(src) { return new Promise(function (res, rej) { var im = new Image(); im.onload = function () { res(im); }; im.onerror = rej; im.src = src; }); }
  function pixels(im) { var c = document.createElement("canvas"); c.width = im.width; c.height = im.height;
    var x = c.getContext("2d"); x.drawImage(im, 0, 0); return x.getImageData(0, 0, c.width, c.height); }

  var diffPx, norPx, dpr = 1, W = 0, H = 0, avgW = 0, meshW = 0, meshH = 0;
  function layout() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = Math.floor(window.innerWidth * dpr); H = Math.floor(window.innerHeight * dpr);
    cv.width = W; cv.height = H; gl.viewport(0, 0, W, H);
    avgW = Math.min(Math.max(window.innerWidth * 0.18, 52), 150);        // narrower on desktop, phone unchanged
    meshW = avgW / EDGE * dpr; meshH = window.innerHeight * 1.08 * dpr;
    var ribs = Math.min(Math.max(avgW * 0.121, 7), 40);                  // consistent rib thickness
    var img = bake(diffPx, norPx, ribs, meshH / TH);
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
    gl.generateMipmap(gl.TEXTURE_2D);                                    // smooth downscale = soft folds
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  }

  var running = true, raf = 0;
  function frame(ms) {
    if (!running) return;
    var t = ms * 0.001;
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
    gl.uniform2f(uRes, W, H); gl.uniform1f(uMW, meshW); gl.uniform1f(uMH, meshH);
    gl.uniform1f(uTop, -0.04 * H); gl.uniform1f(uAmp, avgW * 0.12 * dpr);
    for (var side = 0; side < 2; side++) {
      gl.uniform1f(uSide, side); gl.uniform1f(uTime, t + side * 37);
      gl.drawElements(gl.TRIANGLES, idx.length, gl.UNSIGNED_SHORT, 0);
    }
    raf = window.requestAnimationFrame(frame);
  }

  Promise.all([loadImg(SRC.diff), loadImg(SRC.nor)]).then(function (ims) {
    diffPx = pixels(ims[0]); norPx = pixels(ims[1]);
    layout();
    document.body.classList.add("veil-gl-on");                          // reveal canvas, hide SVG veils
    raf = window.requestAnimationFrame(frame);
    var rt; window.addEventListener("resize", function () { clearTimeout(rt); rt = setTimeout(layout, 150); });
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) { running = false; if (raf) window.cancelAnimationFrame(raf); }
      else if (!running) { running = true; raf = window.requestAnimationFrame(frame); }
    });
  }).catch(function () { /* textures failed: keep the SVG veils */ });
})();
