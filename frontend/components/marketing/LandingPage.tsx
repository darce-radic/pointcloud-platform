import Link from 'next/link'

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-black text-white selection:bg-white selection:text-black font-sans">
      {/* Navigation */}
      <nav className="fixed top-0 w-full z-50 border-b border-[#1a1a1a] bg-black/80 backdrop-blur-md">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-6 h-6 bg-white rounded-sm flex items-center justify-center">
              <div className="w-3 h-3 bg-black rounded-sm" />
            </div>
            <span className="text-white text-sm font-semibold tracking-tight">PointCloud</span>
          </div>
          <div className="flex items-center gap-6 text-sm">
            <Link href="/auth/login" className="text-[#888] hover:text-white transition-colors">
              Sign in
            </Link>
            <Link 
              href="/auth/login" 
              className="bg-white text-black px-4 py-2 rounded-full font-medium hover:bg-[#e0e0e0] transition-colors"
            >
              Get started
            </Link>
          </div>
        </div>
      </nav>

      <main className="pt-32 pb-24">
        {/* Hero Section */}
        <section className="max-w-5xl mx-auto px-6 pt-20 pb-32 text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-[#111] border border-[#222] text-[#888] text-xs font-medium mb-8">
            <span className="w-2 h-2 rounded-full bg-white animate-pulse" />
            Platform v1.0 is now live
          </div>
          <h1 className="text-5xl md:text-7xl font-semibold tracking-tighter mb-8 leading-[1.1]">
            Point cloud processing,<br />
            <span className="text-[#888]">automated by AI.</span>
          </h1>
          <p className="text-lg md:text-xl text-[#666] max-w-2xl mx-auto mb-12 leading-relaxed">
            Upload raw LiDAR and photogrammetry data. Describe your pipeline in plain English. 
            Let our AI agent build, process, and visualize your 3D data in the cloud. No desktop software required.
          </p>
          <div className="flex items-center justify-center gap-4">
            <Link 
              href="/auth/login" 
              className="bg-white text-black px-6 py-3 rounded-full font-medium hover:bg-[#e0e0e0] transition-colors text-sm"
            >
              Start building for free
            </Link>
            <a 
              href="#features" 
              className="px-6 py-3 rounded-full font-medium border border-[#333] text-white hover:bg-[#111] transition-colors text-sm"
            >
              Explore features
            </a>
          </div>
        </section>

        {/* The Problem / Why Section */}
        <section className="border-y border-[#1a1a1a] bg-[#050505]">
          <div className="max-w-7xl mx-auto px-6 py-24">
            <div className="grid md:grid-cols-2 gap-16 items-center">
              <div>
                <h2 className="text-3xl font-semibold tracking-tight mb-6">
                  The old way is broken.
                </h2>
                <div className="space-y-6 text-[#888] text-lg leading-relaxed">
                  <p>
                    Traditional point cloud processing requires expensive desktop software, manual pipeline configuration, and hours of waiting for local machines to render data.
                  </p>
                  <p>
                    Extracting insights—like BIM geometry or road assets—means chaining together disparate tools, scripts, and manual classification steps. It's slow, unscalable, and disconnected from the web.
                  </p>
                </div>
              </div>
              <div className="bg-[#111] border border-[#222] rounded-2xl p-8 font-mono text-sm text-[#666]">
                <div className="flex items-center gap-2 mb-4 pb-4 border-b border-[#222]">
                  <div className="w-3 h-3 rounded-full bg-[#333]" />
                  <div className="w-3 h-3 rounded-full bg-[#333]" />
                  <div className="w-3 h-3 rounded-full bg-[#333]" />
                </div>
                <p className="text-red-400 mb-2">Error: Out of memory</p>
                <p className="mb-2">&gt; pdal pipeline ground_classify.json</p>
                <p className="text-[#444] mb-2">Processing 14.2B points...</p>
                <p className="text-[#444] mb-2">Estimated time: 14 hours</p>
                <p className="text-red-400">&gt; Process killed (SIGKILL)</p>
              </div>
            </div>
          </div>
        </section>

        {/* Features Grid */}
        <section id="features" className="max-w-7xl mx-auto px-6 py-32">
          <div className="text-center mb-20">
            <h2 className="text-3xl md:text-4xl font-semibold tracking-tight mb-4">
              A modern, cloud-native architecture.
            </h2>
            <p className="text-[#666] text-lg">Everything you need to process, analyze, and share 3D data.</p>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {/* Feature 1 */}
            <div className="bg-[#0a0a0a] border border-[#1a1a1a] rounded-2xl p-8 hover:border-[#333] transition-colors">
              <div className="w-10 h-10 bg-[#1a1a1a] rounded-lg flex items-center justify-center mb-6 text-xl">
                ⬡
              </div>
              <h3 className="text-lg font-medium mb-3">AI Workflow Generation</h3>
              <p className="text-[#666] text-sm leading-relaxed">
                Just type "classify ground and generate a DTM". Our LangGraph agent automatically selects the right tools and deploys an n8n pipeline.
              </p>
            </div>

            {/* Feature 2 */}
            <div className="bg-[#0a0a0a] border border-[#1a1a1a] rounded-2xl p-8 hover:border-[#333] transition-colors">
              <div className="w-10 h-10 bg-[#1a1a1a] rounded-lg flex items-center justify-center mb-6 text-xl">
                ◈
              </div>
              <h3 className="text-lg font-medium mb-3">Web-Based 3D Viewer</h3>
              <p className="text-[#666] text-sm leading-relaxed">
                Stream massive datasets instantly. Our Cesium-based viewer supports COPC, 3D Tiles, and synchronizes with 2D maps and 360° panoramas.
              </p>
            </div>

            {/* Feature 3 */}
            <div className="bg-[#0a0a0a] border border-[#1a1a1a] rounded-2xl p-8 hover:border-[#333] transition-colors">
              <div className="w-10 h-10 bg-[#1a1a1a] rounded-lg flex items-center justify-center mb-6 text-xl">
                ▤
              </div>
              <h3 className="text-lg font-medium mb-3">BIM Extraction</h3>
              <p className="text-[#666] text-sm leading-relaxed">
                Automatically extract walls, floors, and ceilings from indoor scans using RANSAC plane-fitting, outputting ready-to-use IFC and DXF files.
              </p>
            </div>

            {/* Feature 4 */}
            <div className="bg-[#0a0a0a] border border-[#1a1a1a] rounded-2xl p-8 hover:border-[#333] transition-colors">
              <div className="w-10 h-10 bg-[#1a1a1a] rounded-lg flex items-center justify-center mb-6 text-xl">
                ◎
              </div>
              <h3 className="text-lg font-medium mb-3">Road Asset Detection</h3>
              <p className="text-[#666] text-sm leading-relaxed">
                Identify traffic signs, street lights, road markings, and kerbs automatically using geometric heuristics and deep learning.
              </p>
            </div>

            {/* Feature 5 */}
            <div className="bg-[#0a0a0a] border border-[#1a1a1a] rounded-2xl p-8 hover:border-[#333] transition-colors">
              <div className="w-10 h-10 bg-[#1a1a1a] rounded-lg flex items-center justify-center mb-6 text-xl">
                ⚡
              </div>
              <h3 className="text-lg font-medium mb-3">Infinite Scalability</h3>
              <p className="text-[#666] text-sm leading-relaxed">
                Powered by distributed workers. Whether it's a 10MB drone scan or a 500GB mobile mapping survey, the platform scales to handle it.
              </p>
            </div>

            {/* Feature 6 */}
            <div className="bg-[#0a0a0a] border border-[#1a1a1a] rounded-2xl p-8 hover:border-[#333] transition-colors">
              <div className="w-10 h-10 bg-[#1a1a1a] rounded-lg flex items-center justify-center mb-6 text-xl">
                ◳
              </div>
              <h3 className="text-lg font-medium mb-3">STAC Discovery API</h3>
              <p className="text-[#666] text-sm leading-relaxed">
                Full STAC v1.0.0 compliance. Programmatically search your datasets by bounding box, datetime, and properties using our REST API.
              </p>
            </div>
          </div>
        </section>

        {/* How it works */}
        <section className="border-t border-[#1a1a1a] py-32">
          <div className="max-w-5xl mx-auto px-6">
            <h2 className="text-3xl font-semibold tracking-tight mb-16 text-center">How it works</h2>
            <div className="grid md:grid-cols-3 gap-12 relative">
              <div className="hidden md:block absolute top-6 left-[20%] right-[20%] h-px bg-gradient-to-r from-transparent via-[#333] to-transparent" />
              
              <div className="relative z-10 text-center">
                <div className="w-12 h-12 bg-black border border-[#333] rounded-full flex items-center justify-center mx-auto mb-6 text-lg font-semibold">1</div>
                <h3 className="text-lg font-medium mb-3">Upload Data</h3>
                <p className="text-[#666] text-sm">Upload raw LAS/LAZ files directly to our secure R2 storage.</p>
              </div>

              <div className="relative z-10 text-center">
                <div className="w-12 h-12 bg-black border border-[#333] rounded-full flex items-center justify-center mx-auto mb-6 text-lg font-semibold">2</div>
                <h3 className="text-lg font-medium mb-3">Prompt the Agent</h3>
                <p className="text-[#666] text-sm">Tell the AI what you need. It builds and executes the workflow.</p>
              </div>

              <div className="relative z-10 text-center">
                <div className="w-12 h-12 bg-white text-black rounded-full flex items-center justify-center mx-auto mb-6 text-lg font-semibold">3</div>
                <h3 className="text-lg font-medium mb-3">View & Export</h3>
                <p className="text-[#666] text-sm">Explore the results in 3D, or export DTMs, IFCs, and GeoJSONs.</p>
              </div>
            </div>
          </div>
        </section>

        {/* Pricing Teaser */}
        <section className="max-w-5xl mx-auto px-6 py-24 bg-[#050505] border border-[#1a1a1a] rounded-3xl mb-32">
          <div className="text-center mb-12">
            <h2 className="text-3xl font-semibold tracking-tight mb-4">Simple, transparent pricing</h2>
            <p className="text-[#666]">Start for free, upgrade when you need more power.</p>
          </div>
          <div className="grid md:grid-cols-3 gap-6 max-w-4xl mx-auto">
            <div className="p-6 border border-[#1a1a1a] rounded-2xl bg-black">
              <h3 className="text-lg font-medium mb-2">Starter</h3>
              <div className="text-3xl font-semibold mb-6">$0<span className="text-sm text-[#666] font-normal">/mo</span></div>
              <ul className="space-y-3 text-sm text-[#888] mb-8">
                <li>✓ 5GB Storage</li>
                <li>✓ Basic PDAL workflows</li>
                <li>✓ 3D Viewer</li>
              </ul>
            </div>
            <div className="p-6 border border-[#333] rounded-2xl bg-[#0a0a0a] relative">
              <div className="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-white text-black text-[10px] font-bold uppercase tracking-wider px-3 py-1 rounded-full">
                Most Popular
              </div>
              <h3 className="text-lg font-medium mb-2">Pro</h3>
              <div className="text-3xl font-semibold mb-6">$49<span className="text-sm text-[#666] font-normal">/mo</span></div>
              <ul className="space-y-3 text-sm text-[#888] mb-8">
                <li className="text-white">✓ 100GB Storage</li>
                <li className="text-white">✓ AI Agent Workflows</li>
                <li className="text-white">✓ BIM & Road Assets</li>
              </ul>
            </div>
            <div className="p-6 border border-[#1a1a1a] rounded-2xl bg-black">
              <h3 className="text-lg font-medium mb-2">Enterprise</h3>
              <div className="text-3xl font-semibold mb-6">Custom</div>
              <ul className="space-y-3 text-sm text-[#888] mb-8">
                <li>✓ Unlimited Storage</li>
                <li>✓ Custom AI Models</li>
                <li>✓ API Access</li>
              </ul>
            </div>
          </div>
          <div className="text-center mt-12">
            <Link 
              href="/auth/login" 
              className="inline-block bg-white text-black px-8 py-3 rounded-full font-medium hover:bg-[#e0e0e0] transition-colors"
            >
              Create your account
            </Link>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-[#1a1a1a] py-12 text-center text-[#666] text-sm">
        <div className="max-w-7xl mx-auto px-6 flex flex-col md:flex-row items-center justify-between">
          <div className="flex items-center gap-2 mb-4 md:mb-0">
            <div className="w-4 h-4 bg-[#333] rounded-sm flex items-center justify-center">
              <div className="w-2 h-2 bg-black rounded-sm" />
            </div>
            <span>© 2026 PointCloud Platform</span>
          </div>
          <div className="flex gap-6">
            <a href="#" className="hover:text-white transition-colors">Twitter</a>
            <a href="#" className="hover:text-white transition-colors">GitHub</a>
            <a href="#" className="hover:text-white transition-colors">Documentation</a>
          </div>
        </div>
      </footer>
    </div>
  )
}
