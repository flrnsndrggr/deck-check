const major = Number(process.versions.node.split(".")[0] || 0);

if (major < 20 || major >= 23) {
  console.error("\nUnsupported Node.js version for apps/web.");
  console.error(`Detected: v${process.versions.node}`);
  console.error("Required: >=20 and <23 (Node 20/22 LTS).");
  console.error("Reason: Next.js static chunk serving is unstable on unsupported versions and can break CSS/JS loading.\n");
  process.exit(1);
}

