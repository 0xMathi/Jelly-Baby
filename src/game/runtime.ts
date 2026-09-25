import * as THREE from 'three/webgpu';
import { SoftBody } from '../physics/soft-body.js';
import { PHYS } from '../physics/constants.js';
import { loadBabyCage } from '../physics/baby-cage.ts';
import { RefractiveLightField } from '../graphics/refractive-light.js';
import { Baby, ABSORPTION } from '../graphics/baby.ts';
import { loadEnvironment } from '../graphics/environment.ts';
import { makeTable } from '../graphics/table.ts';
import { Locomotion } from './locomotion.ts';
import { Input } from './input.ts';
import { JellySound } from './sound.ts';
import { createRenderer, resizeView } from '../graphics/renderer.ts';
import { OpticalTransport } from '../graphics/transport.ts';
import { createComposite } from '../graphics/composite.ts';
import { FixedStepper } from './fixed-step.ts';
import { FruitRush } from './fruit-rush.ts';
import { loadFruits } from '../graphics/fruits.ts';

export async function startGame(stage:(s:string)=>void,fail:(e:unknown)=>void) {
  stage('Starting WebGPU');
  const renderer=await createRenderer(fail);
  document.querySelector('#viewport')!.appendChild(renderer.domElement);
  // Construct audio before the remaining async scene work so the first mobile
  // gesture can unlock Web Audio even while assets and shaders are settling.
  const sound=new JellySound();
  const scene=new THREE.Scene();
  scene.background=new THREE.Color('#e8d9c3');scene.fog=new THREE.Fog('#e8d9c3',2,12);
  const camera=new THREE.PerspectiveCamera(36,1,.001,40);
  camera.position.set(.082,.126,.19);
  stage('Reading the light');
  const environment=await loadEnvironment(renderer,scene);
  stage('Making a little jelly');
  const body=new SoftBody(await loadBabyCage());
  const baby=new Baby(body);scene.add(baby.group);
  const optics=new RefractiveLightField(body.cage.opticalSurface,environment.incoming,ABSORPTION);
  const table=await makeTable(optics,environment);scene.add(table.mesh);
  const composite=createComposite(renderer,scene,camera);
  const rig=new Locomotion(body);
  stage('Picking fruit');
  await loadFruits();
  const game=new FruitRush(scene,camera,baby,optics,sound);
  rig.onContact=(speed,foot)=>sound.contact(speed,foot);
  const physicsClock=new FixedStepper(PHYS.step);
  let lastTime=0,disposed=false;
  const reset=()=>{input.recenter();body.reset();baby.resetFace();physicsClock.reset();};
  const input=new Input(camera,renderer.domElement,body,baby.mesh,rig,sound,reset);
  const transport=new OpticalTransport(optics,body,camera,environment.incoming,fail);
  // Dev-only handle for browser playtests. snapshot() renders offscreen, so it works in a hidden tab (README/portfolio shots).
  if(import.meta.env.DEV)Object.assign(window,{__jelly:{scene,camera,body,game,snapshot:async(width?:number,height?:number)=>{
    // Optional exact output size (e.g. portfolio formats); the view is restored afterwards.
    if(width&&height){renderer.setDrawingBufferSize(width,height,1);camera.aspect=width/height;camera.updateProjectionMatrix();}
    const size=renderer.getDrawingBufferSize(new THREE.Vector2()),target=new THREE.RenderTarget(size.x,size.y);
    baby.update(0);optics.update(renderer,body,true);await transport.update();
    // A hidden tab has no animation loop, so advance the node frame by hand or passes reuse the last frame.
    const internals=renderer as unknown as {_nodes:{nodeFrame:{update():void;frameId:number}};info:{frame:number}};
    internals._nodes.nodeFrame.update();internals.info.frame=internals._nodes.nodeFrame.frameId;
    renderer.setRenderTarget(target);composite.render();renderer.setRenderTarget(null);
    const pixels=await renderer.readRenderTargetPixelsAsync(target,0,0,size.x,size.y) as Uint8Array;target.dispose();
    const canvas=document.createElement('canvas');canvas.width=size.x;canvas.height=size.y;
    const context=canvas.getContext('2d')!,image=context.createImageData(size.x,size.y),stride=Math.ceil(size.x*4/256)*256;
    // WebGPU pads each row (except the last) to 256 bytes; copy row by row.
    for(let y=0;y<size.y;y++)image.data.set(pixels.subarray(y*stride,y*stride+size.x*4),y*size.x*4);
    context.putImageData(image,0,0);if(width&&height)resize();return canvas.toDataURL('image/png');
  }}});
  const resize=()=>resizeView(renderer,camera,input.controls);
  let resizeFrame=0;
  const resizeObserver=new ResizeObserver(()=>{
    cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(resize);
  });
  resizeObserver.observe(document.querySelector('#viewport')!);resize();
  document.querySelector('#reset')!.addEventListener('click',event=>{
    reset();if((event as MouseEvent).detail>0)(event.currentTarget as HTMLButtonElement).blur();
  });
  document.querySelector('#sound')!.addEventListener('click',event=>{
    const muted=sound.toggle(),button=document.querySelector('#sound')!;
    button.setAttribute('aria-pressed',String(muted));button.setAttribute('aria-label',muted?'Enable sound':'Mute sound');
    button.classList.toggle('muted',muted);void sound.unlock().catch(()=>{});
    if((event as MouseEvent).detail>0)(event.currentTarget as HTMLButtonElement).blur();
  });
  stage('Settling in');
  // Let contact establish itself before displaying the first frame.
  for(let i=0;i<80;i++){rig.step(PHYS.step);body.step(PHYS.step);}
  body.updateSurface();baby.update();input.update(1);
  optics.update(renderer,body,true);
  await transport.update();
  stage('Compiling the material');
  await renderer.compileAsync(scene,camera);
  stage('Drawing the first frame');
  composite.render();
  // Fence first-frame GPU work so validation/OOM cannot masquerade as a successful boot.
  const backend=renderer.backend as unknown as {device:GPUDevice};
  await backend.device.queue.onSubmittedWorkDone();
  lastTime=performance.now();
  const frame=(time:number)=>{
    if(disposed)return;
    try {
      const dt=Math.min(.05,Math.max(0,(time-lastTime)/1000));lastTime=time;
      if(document.hidden){physicsClock.reset();return;}
      const steps=physicsClock.advance(dt,()=>{
        input.step(PHYS.step);rig.step(PHYS.step);body.step(PHYS.step);input.afterPhysicsStep();rig.afterStep();
      });
      if(steps&&body.surfaceDirty) {
        if(!body.isFinite())throw new Error('The soft-body simulation produced an invalid state');
        body.updateSurface();
      }
      baby.update(dt);
      input.update(dt);
      game.update(dt,body.center);
      transport.follow();
      optics.update(renderer,body);
      table.mesh.position.x=body.center.x;table.mesh.position.z=body.center.z;
      void transport.update().catch(fail);
      composite.render();
    }catch(error){fail(error);}
  };
  await renderer.setAnimationLoop(frame);
  const dispose=()=>{
    if(disposed)return;disposed=true;
    void renderer.setAnimationLoop(null);input.dispose();sound.dispose();transport.dispose();resizeObserver.disconnect();cancelAnimationFrame(resizeFrame);
    game.dispose();composite.dispose();baby.dispose();table.dispose();environment.dispose();optics.dispose();renderer.dispose();
  };
  window.addEventListener('pagehide',event=>{if(!event.persisted)dispose();});
  if(import.meta.hot)import.meta.hot.dispose(dispose);
  return {stop:()=>{disposed=true;input.clear();game.dispose();sound.dispose();transport.dispose();void renderer.setAnimationLoop(null);}};
}
