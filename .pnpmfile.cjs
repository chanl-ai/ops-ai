// openapi-typescript 7 writes the SDK types with the TypeScript compiler API (ts.factory), which typescript 7 does not
// ship. Its peer dependency would resolve to the workspace's typescript 7, so it gets its own typescript 5 instead.
// Remove this file when openapi-typescript supports typescript 7.
function readPackage(pkg) {
  if (pkg.name === 'openapi-typescript' && pkg.peerDependencies?.typescript) {
    delete pkg.peerDependencies.typescript;
    pkg.dependencies = { ...pkg.dependencies, typescript: '5.9.3' };
  }
  return pkg;
}

module.exports = { hooks: { readPackage } };
