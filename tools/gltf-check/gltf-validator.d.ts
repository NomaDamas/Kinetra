// Types for the part of `gltf-validator` this tool uses (the package ships none). API: its README, "Full usage".
declare module "gltf-validator" {
  interface Message {
    code: string;
    message: string;
    severity: number;
    pointer?: string;
  }
  interface Report {
    issues: { numErrors: number; numWarnings: number; numInfos: number; numHints: number; messages: Message[]; truncated: boolean };
    info: { version: string; generator?: string; extensionsUsed?: string[]; totalTriangleCount?: number };
  }
  const validator: {
    validateBytes(data: Uint8Array, options?: { uri?: string; maxIssues?: number }): Promise<Report>;
  };
  export default validator;
}
