import * as THREE from 'three/webgpu';
import { FRUITS, FRUIT_NAMES, type FruitName, makeFruit, makeFruitShadow, disposeFruitAssets, fruitFootprint, SHADOW_SCALE } from '../graphics/fruits.ts';
import { JELLY_FLAVORS, DEFAULT_JELLY_FLAVOR } from '../graphics/jelly-flavors.ts';
import type { Baby } from '../graphics/baby.ts';
import type { RefractiveLightField } from '../graphics/refractive-light.js';
import type { JellySound } from './sound.ts';

const ROUND_SECONDS=60;
const LIVE_FRUITS=5;
const SPAWN_MIN=.09, SPAWN_MAX=.26, SPAWN_SPREAD=.9, FORGET_BEYOND=.9;
const JELLY_REACH=.048;
const CHAIN_WINDOW=1.2, COMBO_EVERY=5, COMBO_BONUS=3, COMBO_MIN_TOP=175;
const SCORES_KEY='fruit-rush:scores';

type Live={name:FruitName;root:THREE.Group;fruit:THREE.Group;shadow:THREE.Mesh;footprint:number;age:number;collectedFor:number;phase:number};
type Score={score:number;at:number};
type State='free'|'playing';

const fruitDots=FRUIT_NAMES.map(name=>`<span style="background:${FRUITS[name].color}"></span>`).join('');

export function fruitRushMarkup() {
  return `<div class="hud" hidden><span class="hud-time">1:00</span><span class="hud-dot"></span><span class="hud-score">0</span></div>
  <div class="combo" aria-live="polite"></div>
  <button class="round-open" type="button" title="60 seconds of gathering. Chain five quickly for a combo."><span class="round-open-dots">${fruitDots}</span>play fruit rush <kbd>enter</kbd></button>
  <section class="round-card" aria-live="polite" hidden>
    <button class="round-close" type="button" aria-label="Close and just wander" title="Close · esc">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M6 6l12 12M18 6 6 18"/></svg>
    </button>
    <div class="round-result">
      <p class="eyebrow">time's up</p>
      <p class="round-best" hidden>new best!</p>
      <p class="round-score"><span class="round-score-value">0</span><span class="round-score-unit">fruits</span></p>
      <ul class="round-tally"></ul>
    </div>
    <ol class="round-scores" hidden></ol>
    <button class="round-start" type="button">Play again <kbd>enter</kbd></button>
  </section>`;
}

function easeOutBack(t:number) {const c=1.9;return 1+(c+1)*(t-1)**3+c*(t-1)**2;}

export class FruitRush {
  private state:State='free';
  private timeLeft=ROUND_SECONDS;
  private score=0;
  private bonus=0;
  private tally=new Map<FruitName,number>();
  private streak=0;
  private sinceLast=99;
  private readonly live:Live[]=[];
  private readonly group=new THREE.Group();
  private readonly color=new THREE.Color(JELLY_FLAVORS[DEFAULT_JELLY_FLAVOR].surface);
  private readonly targetColor=this.color.clone();
  private readonly absorption:[number,number,number]=[...JELLY_FLAVORS[DEFAULT_JELLY_FLAVOR].absorption];
  private targetAbsorption:readonly [number,number,number]=JELLY_FLAVORS[DEFAULT_JELLY_FLAVOR].absorption;
  private readonly hud=document.querySelector<HTMLDivElement>('.hud')!;
  private readonly time=this.hud.querySelector<HTMLSpanElement>('.hud-time')!;
  private readonly scoreLabel=this.hud.querySelector<HTMLSpanElement>('.hud-score')!;
  private readonly dot=this.hud.querySelector<HTMLSpanElement>('.hud-dot')!;
  private readonly card=document.querySelector<HTMLElement>('.round-card')!;
  private readonly openButton=document.querySelector<HTMLButtonElement>('.round-open')!;
  private readonly comboLabel=document.querySelector<HTMLDivElement>('.combo')!;
  private readonly screen=new THREE.Vector3();
  private readonly abort=new AbortController();
  private readonly baby:Baby;
  private readonly optics:RefractiveLightField;
  private readonly sound:JellySound;
  private readonly camera:THREE.Camera;

  constructor(scene:THREE.Scene,camera:THREE.Camera,baby:Baby,optics:RefractiveLightField,sound:JellySound) {
    this.camera=camera;this.baby=baby;this.optics=optics;this.sound=sound;
    scene.add(this.group);
    const {signal}=this.abort;
    const click=(selector:string,action:()=>void)=>document.querySelector(selector)!.addEventListener('click',event=>{
      action();if((event as MouseEvent).detail>0)(event.currentTarget as HTMLButtonElement).blur();
    },{signal});
    click('.round-start',()=>this.start());
    click('.round-open',()=>this.start());
    click('.round-close',()=>this.closeCard());
    window.addEventListener('keydown',event=>{
      if(event.repeat||this.state==='playing')return;
      if(event.code==='Enter')this.start();
      if(event.code==='Escape')this.closeCard();
    },{signal});
    this.renderScores(this.loadScores(),-1);
  }

  private start() {
    this.state='playing';this.timeLeft=ROUND_SECONDS;this.score=0;this.bonus=0;this.streak=0;this.tally.clear();
    this.card.hidden=true;this.openButton.hidden=true;this.hud.hidden=false;this.scoreLabel.textContent='0';
    void this.sound.unlock().catch(()=>{});
  }

  /** Free play: the card goes away, fruit keeps coming, nothing is scored. */
  private closeCard() {
    if(this.card.hidden)return;
    this.card.hidden=true;this.openButton.hidden=false;
  }

  private finish() {
    this.state='free';this.hud.hidden=true;
    for(const fruit of this.live)if(fruit.collectedFor<0)fruit.collectedFor=0;
    const scores=this.loadScores(),entry={score:this.score,at:Date.now()};
    scores.push(entry);scores.sort((a,b)=>b.score-a.score||a.at-b.at);scores.length=Math.min(scores.length,5);
    this.saveScores(scores);
    this.card.querySelector<HTMLElement>('.round-best')!.hidden=!(this.score>0&&scores[0]===entry);
    this.card.querySelector('.round-score-value')!.textContent=String(this.score);
    this.card.querySelector('.round-score-unit')!.textContent=this.score===1?'point':'points';
    this.card.querySelector('.round-tally')!.innerHTML=FRUIT_NAMES.filter(name=>this.tally.has(name)).map(name=>
      `<li><span style="background:${FRUITS[name].color}"></span>${this.tally.get(name)} ${FRUITS[name].label}</li>`).join('')+
      (this.bonus?`<li class="round-tally-bonus">+${this.bonus} combo bonus</li>`:'');
    this.renderScores(scores,scores.indexOf(entry));
    this.card.hidden=false;this.card.classList.remove('pop');void this.card.offsetWidth;this.card.classList.add('pop');
    this.sound.roundOver();
  }

  private loadScores():Score[] {
    try {
      const parsed:unknown=JSON.parse(localStorage.getItem(SCORES_KEY)??'[]');
      return Array.isArray(parsed)?parsed.filter((s):s is Score=>typeof s?.score==='number'&&typeof s?.at==='number'):[];
    } catch {return [];}
  }
  private saveScores(scores:Score[]) {try{localStorage.setItem(SCORES_KEY,JSON.stringify(scores));}catch{/* private mode: scores last one session */}}
  private renderScores(scores:Score[],highlight:number) {
    const list=this.card.querySelector<HTMLOListElement>('.round-scores')!;
    list.hidden=scores.length===0;
    list.innerHTML=scores.map((s,i)=>`<li${i===highlight?' class="current"':''}><span>${s.score} <small>pt${s.score===1?'':'s'}</small></span><time>${new Date(s.at).toLocaleDateString(undefined,{day:'numeric',month:'short'})}</time></li>`).join('');
  }

  private spawn(center:THREE.Vector3) {
    const name=FRUIT_NAMES[Math.floor(Math.random()*FRUIT_NAMES.length)];
    const footprint=fruitFootprint(name);
    const root=new THREE.Group(),fruit=makeFruit(name),shadow=makeFruitShadow(footprint);
    root.add(shadow,fruit);
    // Spawn ahead of the camera so new fruit is (mostly) on screen.
    const facing=Math.atan2(center.z-this.camera.position.z,center.x-this.camera.position.x);
    for(let attempt=0;attempt<12;attempt++) {
      const angle=facing+(Math.random()-.5)*2*SPAWN_SPREAD,distance=SPAWN_MIN+Math.random()*(SPAWN_MAX-SPAWN_MIN);
      root.position.set(center.x+Math.cos(angle)*distance,0,center.z+Math.sin(angle)*distance);
      if(this.live.every(other=>other.root.position.distanceTo(root.position)>.09))break;
    }
    fruit.rotation.y=Math.random()*Math.PI*2;fruit.scale.setScalar(0);
    this.group.add(root);
    this.live.push({name,root,fruit,shadow,footprint,age:0,collectedFor:-1,phase:Math.random()*6});
  }

  private collect(fruit:Live,center:THREE.Vector3) {
    fruit.collectedFor=0;
    this.streak=this.sinceLast<CHAIN_WINDOW?this.streak+1:0;this.sinceLast=0;
    const chain=this.streak+1,combo=chain%COMBO_EVERY===0;
    // Bonus grows with the chain: x5 +3, x10 +6, x15 +9 ...
    const bonus=combo&&this.state==='playing'?chain/COMBO_EVERY*COMBO_BONUS:0;
    if(this.state==='playing') {
      this.score+=1+bonus;this.bonus+=bonus;this.scoreLabel.textContent=String(this.score);
      this.tally.set(fruit.name,(this.tally.get(fruit.name)??0)+1);
    }
    this.sound.collect(this.streak);
    if(combo){this.sound.combo();this.showCombo(chain,bonus,center);}
    const look=JELLY_FLAVORS[FRUITS[fruit.name].flavor];
    this.targetColor.set(look.surface);this.targetAbsorption=look.absorption;
    this.dot.style.background=FRUITS[fruit.name].color;
    const specimen=document.querySelector('.specimen');
    if(specimen)specimen.innerHTML=`<span style="background:${FRUITS[fruit.name].color}"></span> ${FRUITS[fruit.name].label} &nbsp; / &nbsp; 7 cm of happiness`;
    this.hud.classList.remove('bump');void this.hud.offsetWidth;this.hud.classList.add('bump');
  }

  private showCombo(chain:number,bonus:number,center:THREE.Vector3) {
    // Pop the label just above the jelly's head.
    this.screen.set(center.x,center.y+.045,center.z).project(this.camera);
    this.comboLabel.style.left=`${(this.screen.x+1)/2*innerWidth}px`;
    // Clamp below the HUD so the two never overlap.
    this.comboLabel.style.top=`${Math.max(COMBO_MIN_TOP,(1-this.screen.y)/2*innerHeight)}px`;
    this.comboLabel.innerHTML=`<span class="combo-label">combo ×${chain}!</span>${bonus?`<span class="combo-bonus">+${bonus}</span>`:''}`;
    this.comboLabel.classList.remove('show');void this.comboLabel.offsetWidth;this.comboLabel.classList.add('show');
  }

  update(dt:number,center:THREE.Vector3) {
    this.sinceLast+=dt;
    if(this.state==='playing') {
      this.timeLeft-=dt;
      const shown=Math.max(0,Math.ceil(this.timeLeft));
      this.time.textContent=`${Math.floor(shown/60)}:${String(shown%60).padStart(2,'0')}`;
      this.hud.classList.toggle('hurry',this.timeLeft<10);
      if(this.timeLeft<=0)this.finish();
    }
    // Fruit keeps coming during a round and in free play; the open card keeps the table clean.
    if(this.state==='playing'||this.card.hidden)while(this.live.filter(f=>f.collectedFor<0).length<LIVE_FRUITS)this.spawn(center);
    for(let i=this.live.length-1;i>=0;i--) {
      const fruit=this.live[i];fruit.age+=dt;
      const dx=fruit.root.position.x-center.x,dz=fruit.root.position.z-center.z,distance=Math.hypot(dx,dz);
      if(fruit.collectedFor<0) {
        // Picked up once the jelly's edge reaches into the fruit's footprint.
        if(distance<JELLY_REACH+fruit.footprint*.75)this.collect(fruit,center);
        else if(distance>FORGET_BEYOND)fruit.collectedFor=0;
        const grow=easeOutBack(Math.min(1,fruit.age/.38)),breathe=Math.sin(fruit.age*2.6+fruit.phase)*.025;
        fruit.fruit.scale.set(grow*(1-breathe*.5),grow*(1+breathe),grow*(1-breathe*.5));
        fruit.shadow.scale.setScalar(fruit.footprint*SHADOW_SCALE*Math.min(1,grow));
      } else {
        // Shrink into the jelly (or just vanish when forgotten or the round ended).
        fruit.collectedFor+=dt;
        const t=Math.min(1,fruit.collectedFor/.2),s=(1-t)*(1+t*.4);
        fruit.fruit.scale.setScalar(s);fruit.shadow.scale.setScalar(fruit.footprint*SHADOW_SCALE*(1-t));
        if(distance<FORGET_BEYOND)fruit.root.position.set(fruit.root.position.x-dx*t*.35,fruit.root.position.y,fruit.root.position.z-dz*t*.35);
        if(t>=1){this.group.remove(fruit.root);this.live.splice(i,1);}
      }
    }
    this.blendFlavor(dt);
  }

  private blendFlavor(dt:number) {
    const k=1-Math.exp(-9*dt);
    let settled=Math.abs(this.color.r-this.targetColor.r)+Math.abs(this.color.g-this.targetColor.g)+Math.abs(this.color.b-this.targetColor.b)<1e-3;
    for(let i=0;i<3;i++)settled&&=Math.abs(this.absorption[i]-this.targetAbsorption[i])<.05;
    if(settled)return;
    this.color.lerp(this.targetColor,k);
    for(let i=0;i<3;i++)this.absorption[i]+=(this.targetAbsorption[i]-this.absorption[i])*k;
    this.baby.setLook(this.color,this.absorption);this.optics.setAbsorption(this.absorption);
  }

  dispose() {this.abort.abort();this.group.removeFromParent();disposeFruitAssets();}
}
