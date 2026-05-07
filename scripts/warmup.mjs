const BASE_URL = process.env.SITE_URL || "https://carstrims.vercel.app";
const API_URL = process.env.API_URL || "https://your-backend.railway.app";

const PAGES = [
  "/",
  "/feed",
  "/auth/login",
  "/auth/register",
  "/auth/forgot-password",
  "/dashboard/dealer",
  "/dashboard/super-admin",
  "/dashboard/partner",
  "/dashboard/staff",
  "/dashboard/user",
];

const API_ENDPOINTS = [
  "/api/v1/public/cars?limit=5",
  "/api/v1/public/dealers?limit=5",
  "/health",
];

async function warmup() {
  console.log("🔥 Warming up CARSTRIMS...");
  
  for (const page of PAGES) {
    try {
      const res = await fetch(`${BASE_URL}${page}`);
      console.log(`✅ ${page} — ${res.status}`);
    } catch (e) {
      console.log(`❌ ${page} — failed`);
    }
  }

  for (const endpoint of API_ENDPOINTS) {
    try {
      const res = await fetch(`${API_URL}${endpoint}`);
      console.log(`✅ API${endpoint} — ${res.status}`);
    } catch (e) {
      console.log(`❌ API${endpoint} — failed`);
    }
  }

  console.log("✅ Warmup complete!");
}

warmup();
