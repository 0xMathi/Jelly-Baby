import * as THREE from 'three/webgpu';
import type { JellyFlavorName } from './jelly-flavors.ts';

type Fruit={readonly flavor:JellyFlavorName;readonly radius:number;readonly color:string;readonly label:string};

// Deliberately oversized and plump next to the 7 cm jelly (real grapes are ~1 cm radius).
export const FRUITS={
  strawberry:{flavor:'strawberry',radius:.020,color:'#d7263d',label:'strawberry'},
  grape:{flavor:'grape',radius:.016,color:'#5b2a86',label:'grape'},
  blueberry:{flavor:'blueberry',radius:.014,color:'#3b4f9c',label:'blueberry'},
  kumquat:{flavor:'orange',radius:.018,color:'#f28a1a',label:'kumquat'},
  mirabelle:{flavor:'lemon',radius:.017,color:'#f2c230',label:'mirabelle'},
  greenGrape:{flavor:'lime',radius:.016,color:'#9cc43c',label:'green grape'},
} as const satisfies Record<string,Fruit>;

export type FruitName=keyof typeof FRUITS;
export const FRUIT_NAMES=Object.keys(FRUITS) as FruitName[];

// ponytail: placeholder spheres; swapped for the Blender GLBs once they exist.
const materials=new Map<FruitName,THREE.MeshPhysicalNodeMaterial>();
const sphere=new THREE.SphereGeometry(1,48,32).translate(0,1,0);

/** A fruit whose origin sits on the table at its bottom centre. */
export function makeFruit(name:FruitName) {
  let material=materials.get(name);
  if(!material) {
    material=new THREE.MeshPhysicalNodeMaterial({color:FRUITS[name].color,roughness:.32,clearcoat:.6,clearcoatRoughness:.18,sheen:.3});
    materials.set(name,material);
  }
  const mesh=new THREE.Mesh(sphere,material);
  mesh.scale.setScalar(FRUITS[name].radius);
  const group=new THREE.Group();group.add(mesh);
  return group;
}

let shadowTexture:THREE.CanvasTexture|null=null;
const shadowPlane=new THREE.PlaneGeometry(1,1).rotateX(-Math.PI/2);
let shadowMaterial:THREE.MeshBasicNodeMaterial|null=null;

/** Soft contact shadow; the scene has no shadow-casting light for props. */
export function makeFruitShadow(radius:number) {
  if(!shadowMaterial) {
    const canvas=document.createElement('canvas');canvas.width=canvas.height=64;
    const ctx=canvas.getContext('2d')!;
    const gradient=ctx.createRadialGradient(32,32,0,32,32,32);
    gradient.addColorStop(0,'rgba(0,0,0,.62)');gradient.addColorStop(.45,'rgba(0,0,0,.28)');gradient.addColorStop(1,'rgba(0,0,0,0)');
    ctx.fillStyle=gradient;ctx.fillRect(0,0,64,64);
    shadowTexture=new THREE.CanvasTexture(canvas);
    shadowMaterial=new THREE.MeshBasicNodeMaterial({map:shadowTexture,transparent:true,depthWrite:false,color:'#3a2a1a'});
  }
  const mesh=new THREE.Mesh(shadowPlane,shadowMaterial);
  mesh.scale.setScalar(radius*3.4);mesh.position.y=.0002;mesh.renderOrder=0;
  return mesh;
}

export function disposeFruitAssets() {
  materials.forEach(m=>m.dispose());materials.clear();
  sphere.dispose();shadowPlane.dispose();shadowMaterial?.dispose();shadowTexture?.dispose();
}
