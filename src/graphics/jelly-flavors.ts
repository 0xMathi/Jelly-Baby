export type JellyFlavor = {
  readonly surface:string;
  readonly absorption:readonly [number,number,number];
};

export const JELLY_FLAVORS={
  lime:{surface:'#eaffd4',absorption:[48,3.2,85]},
  strawberry:{surface:'#ffc2ce',absorption:[10,44,56]},
  blueberry:{surface:'#a9d9ff',absorption:[14,8,3]},
  lemon:{surface:'#fff06a',absorption:[8,8,112]},
  grape:{surface:'#e0c2ff',absorption:[26,72,12]},
  orange:{surface:'#ffd2a1',absorption:[5,30,118]},
  pear:{surface:'#f2ffcc',absorption:[18,3,78]},
  raspberry:{surface:'#ffc6e0',absorption:[4,64,16]},
} as const satisfies Record<string,JellyFlavor>;

export type JellyFlavorName=keyof typeof JELLY_FLAVORS;
export const DEFAULT_JELLY_FLAVOR:JellyFlavorName='lime';
