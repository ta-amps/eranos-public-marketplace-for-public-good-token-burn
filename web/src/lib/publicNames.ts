/** Public text says Fabric, never the old code names, inside a worker's name too. Only the page changes; stored names stay. */
export function publicNames(text: string): string {
  return text.replace(/(?<![a-z0-9])(?:herma|tessera)(?![a-z0-9])/gi, "fabric");
}
