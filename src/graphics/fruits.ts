import * as THREE from 'three/webgpu';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { saturation, vertexColor } from 'three/tsl';
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

type Finish={roughness:number;clearcoat:number;sheen:number};
// Glossy skins get clearcoat; grapes and blueberries get a dusty sheen "bloom".
const SKIN:Record<FruitName,Finish>={
  strawberry:{roughness:.28,clearcoat:.8,sheen:0},
  grape:{roughness:.42,clearcoat:.25,sheen:.25},
  blueberry:{roughness:.55,clearcoat:0,sheen:.35},
  kumquat:{roughness:.26,clearcoat:.7,sheen:0},
  mirabelle:{roughness:.36,clearcoat:.4,sheen:.12},
  greenGrape:{roughness:.3,clearcoat:.4,sheen:.12},
};
const SKIN_SATURATION=1.8, SKIN_BRIGHTNESS=.8;
const templates=new Map<FruitName,THREE.Object3D>();

function dress(root:THREE.Object3D,name:FruitName) {
  const cache=new Map<string,THREE.MeshPhysicalNodeMaterial>();
  const make=(key:string)=>{
    const skin=SKIN[name];
    if(key.startsWith('skin')) {
      const material=new THREE.MeshPhysicalNodeMaterial({roughness:skin.roughness,clearcoat:skin.clearcoat,clearcoatRoughness:.12,sheen:skin.sheen,sheenRoughness:.6,sheenColor:new THREE.Color('#dfe6ff')});
      // AgX output desaturates bright albedo; pre-boost so fruit reads as vividly as it does in Blender.
      material.colorNode=saturation(vertexColor(),SKIN_SATURATION).mul(SKIN_BRIGHTNESS);
      return material;
    }
    if(key.startsWith('seed'))return new THREE.MeshPhysicalNodeMaterial({color:'#d9a93a',roughness:.35,clearcoat:.4});
    if(key.startsWith('leaf'))return new THREE.MeshPhysicalNodeMaterial({color:'#3f7d1f',roughness:.5,sheen:.4,sheenColor:new THREE.Color('#b9e28c')});
    if(key.startsWith('stem'))return new THREE.MeshPhysicalNodeMaterial({color:'#6d6a2c',roughness:.65});
    throw new Error(`Unexpected material "${key}" in ${name}.glb`);
  };
  root.traverse(object=>{
    if(!(object instanceof THREE.Mesh))return;
    const key=(object.material as THREE.Material).name;
    (object.material as THREE.Material).dispose();
    let material=cache.get(key);
    if(!material){material=make(key);cache.set(key,material);}
    object.material=material;
  });
}

/** Loads the Blender-built fruit models (scripts/blender/fruits.py); call once before makeFruit. */
export async function loadFruits() {
  const loader=new GLTFLoader();
  await Promise.all(FRUIT_NAMES.map(async name=>{
    const gltf=await loader.loadAsync(new URL(`../assets/fruits/${name}.glb`,import.meta.url).href);
    dress(gltf.scene,name);templates.set(name,gltf.scene);
  }));
}

/** A fruit whose origin sits on the table at its bottom centre. Models are 2 units across. */
export function makeFruit(name:FruitName) {
  const template=templates.get(name);
  if(!template)throw new Error('makeFruit called before loadFruits');
  const model=template.clone();
  model.scale.setScalar(FRUITS[name].radius);
  const group=new THREE.Group();group.add(model);
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
    gradient.addColorStop(0,'rgba(0,0,0,.85)');gradient.addColorStop(.4,'rgba(0,0,0,.45)');gradient.addColorStop(1,'rgba(0,0,0,0)');
    ctx.fillStyle=gradient;ctx.fillRect(0,0,64,64);
    shadowTexture=new THREE.CanvasTexture(canvas);
    shadowMaterial=new THREE.MeshBasicNodeMaterial({map:shadowTexture,transparent:true,depthWrite:false,color:'#3a2a1a'});
  }
  const mesh=new THREE.Mesh(shadowPlane,shadowMaterial);
  mesh.scale.setScalar(radius*2.6);mesh.position.y=.0002;mesh.renderOrder=0;
  return mesh;
}

export function disposeFruitAssets() {
  const materials=new Set<THREE.Material>();
  templates.forEach(root=>root.traverse(object=>{
    if(object instanceof THREE.Mesh){object.geometry.dispose();materials.add(object.material as THREE.Material);}
  }));
  materials.forEach(m=>m.dispose());templates.clear();
  shadowPlane.dispose();shadowMaterial?.dispose();shadowTexture?.dispose();
}
