import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, useMemo, useCallback } from "react";
import { MapView } from "./components/Map/MapView";
import type { MapLocation } from "./components/Map/MapView";
import { SearchBar } from "./components/Search/SearchBar";
import { FilterPanel, type FilterState } from "./components/Filter/FilterPanel";
import { ResultList } from "./components/Panel/ResultList";
import { EntryDetail } from "./components/Panel/EntryDetail";
import { LocationPage } from "./pages/LocationPage";
import EntryPage from "./pages/EntryPage";
import { useEntries, useLocations, useSearch } from "./api/hooks";
import { ChevronUp, ChevronDown, Compass, Map } from "lucide-react";
import { getLanguage, type Language } from "./lib/language";

const queryClient = new QueryClient();

function haversineDistance(
  lat1: number, lon1: number,
  lat2: number, lon2: number
): number {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function HomePage() {
  const [filters, setFilters] = useState<FilterState>({ dynasty: "", locationType: "", era: "" });
  const [language, setLanguage] = useState<Language>(getLanguage);
  const { data: locations = [] } = useLocations({
    dynasty: filters.dynasty || undefined,
    type: filters.locationType || undefined,
  });
  const { data: entries = [] } = useEntries({
    dynasty: filters.dynasty || undefined,
    era: filters.era || undefined,
  });
  const [searchQuery, setSearchQuery] = useState("");
  const { data: searchResults } = useSearch(searchQuery);
  const [selectedEntryId, setSelectedEntryId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [locationFilter, setLocationFilter] = useState<{
    lat: number;
    lng: number;
    radiusKm: number;
  } | null>(null);
  const [focusTarget, setFocusTarget] = useState<{
    locations: Array<{ latitude: number; longitude: number }>;
  } | null>(null);

  const displayEntriesRaw = searchQuery && searchResults ? searchResults : entries;
  const displayLocations = searchQuery && searchResults
    ? searchResults.flatMap((e) => e.locations).filter((l, i, arr) => arr.findIndex((x) => x.id === l.id) === i)
    : locations;

  const displayEntries = useMemo(() => {
    if (!locationFilter) return displayEntriesRaw;
    return displayEntriesRaw.filter((entry) =>
      entry.locations.some((loc) => {
        const dist = haversineDistance(
          locationFilter.lat,
          locationFilter.lng,
          loc.latitude,
          loc.longitude
        );
        return dist <= locationFilter.radiusKm;
      })
    );
  }, [displayEntriesRaw, locationFilter]);

  const handleSelectEntry = useCallback(
    (id: number) => {
      setSelectedEntryId(id);
      const entry = displayEntriesRaw.find((e) => e.id === id);
      if (entry && entry.locations.length > 0) {
        setFocusTarget({
          locations: entry.locations.map((loc) => ({
            latitude: loc.latitude,
            longitude: loc.longitude,
          })),
        });
      }
    },
    [displayEntriesRaw]
  );

  const handleMarkerClick = useCallback((location: MapLocation) => {
    setLocationFilter({
      lat: location.latitude,
      lng: location.longitude,
      radiusKm: 10,
    });
  }, []);

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <header className="h-16 flex items-center px-5 gap-4 z-20 relative overflow-hidden"
        style={{
          background: 'linear-gradient(135deg, #1a1a2e 0%, #222240 40%, #2a2a4a 100%)',
          borderBottom: '1px solid rgba(201, 168, 76, 0.3)',
        }}
      >
        {/* Decorative background pattern */}
        <div className="absolute inset-0 opacity-5"
          style={{
            backgroundImage: `repeating-linear-gradient(45deg, transparent, transparent 20px, rgba(201,168,76,0.3) 20px, rgba(201,168,76,0.3) 21px)`,
          }}
        />

        {/* Logo */}
        <div className="flex items-center gap-2.5 relative z-10 shrink-0">
          <div className="w-9 h-9 rounded-lg flex items-center justify-center animate-glow"
            style={{ background: 'linear-gradient(135deg, #c9a84c, #e8d5a0)' }}>
            <Compass className="h-5 w-5 text-[#1a1a2e]" strokeWidth={2.5} />
          </div>
          <div>
            <h1 className="text-lg font-bold text-white tracking-wide font-serif-display">HiSMap</h1>
            <p className="text-[10px] text-amber-200/50 -mt-0.5 tracking-widest uppercase">Historical Journey Map</p>
          </div>
        </div>

        {/* Search */}
        <div className="flex-1 relative z-10 max-w-xl">
          <SearchBar onSearch={setSearchQuery} />
        </div>

        {/* Filters */}
        <div className="relative z-10 shrink-0">
          <FilterPanel onChange={setFilters} onLanguageChange={setLanguage} />
        </div>
      </header>

      {/* Main Content */}
      <div className="flex-1 flex relative overflow-hidden">
        {/* Sidebar */}
        <aside className="hidden md:flex w-80 flex-col border-r z-20 shrink-0"
          style={{
            background: 'linear-gradient(180deg, #faf8f3 0%, #f5f0e8 100%)',
            borderColor: 'rgba(0,0,0,0.08)',
          }}
        >
          <div className="px-4 py-3 border-b flex items-center gap-2 shrink-0"
            style={{ borderColor: 'rgba(0,0,0,0.06)', background: 'rgba(255,255,255,0.5)' }}>
            <Map className="h-4 w-4 text-amber-600" />
            <span className="text-sm font-medium text-gray-700">
              {displayEntries.length} 条游记
            </span>
            {locationFilter && (
              <span className="text-xs text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full ml-auto">
                位置筛选中
              </span>
            )}
          </div>
          <div className="flex-1 overflow-y-auto">
            <ResultList
              entries={displayEntries}
              onSelect={handleSelectEntry}
              selectedId={selectedEntryId}
              locationFilter={locationFilter}
              onClearFilter={() => setLocationFilter(null)}
              language={language}
            />
          </div>
        </aside>

        {/* Map */}
        <div className="flex-1 relative z-0">
          <MapView
            locations={displayLocations}
            focusTarget={focusTarget}
            entries={displayEntriesRaw}
            onMarkerClick={handleMarkerClick}
          />
        </div>

        {/* Desktop Detail Panel */}
        {selectedEntryId && (
          <div className="hidden md:block absolute right-0 top-0 bottom-0 w-96 z-30 animate-slide-in-right"
            style={{
              background: 'rgba(255,255,255,0.95)',
              backdropFilter: 'blur(16px)',
              borderLeft: '1px solid rgba(0,0,0,0.08)',
              boxShadow: '-8px 0 30px rgba(0,0,0,0.08)',
            }}
          >
            <EntryDetail entryId={selectedEntryId} onClose={() => setSelectedEntryId(null)} language={language} />
          </div>
        )}

        {/* Mobile Drawer */}
        <div
          className={`md:hidden absolute bottom-0 left-0 right-0 z-30 transition-all duration-500 ease-out ${
            drawerOpen ? "translate-y-0" : "translate-y-[calc(100%-3.5rem)]"
          }`}
          style={{
            maxHeight: "75vh",
            background: 'rgba(255,255,255,0.95)',
            backdropFilter: 'blur(16px)',
            borderTop: '1px solid rgba(0,0,0,0.08)',
            boxShadow: '0 -8px 30px rgba(0,0,0,0.1)',
            borderRadius: '20px 20px 0 0',
          }}
        >
          {/* Drawer Handle */}
          <button
            onClick={() => setDrawerOpen(!drawerOpen)}
            className="w-full flex flex-col items-center py-2.5 group"
          >
            <div className="w-10 h-1 rounded-full bg-gray-300 group-hover:bg-gray-400 transition-colors mb-1.5" />
            <div className="flex items-center gap-2">
              {drawerOpen ? <ChevronDown className="h-4 w-4 text-gray-400" /> : <ChevronUp className="h-4 w-4 text-gray-400" />}
              <span className="text-sm text-gray-500 font-medium">{displayEntries.length} 条游记</span>
            </div>
          </button>
          <div className="overflow-y-auto" style={{ maxHeight: "calc(75vh - 4rem)" }}>
            {selectedEntryId ? (
              <EntryDetail entryId={selectedEntryId} onClose={() => setSelectedEntryId(null)} language={language} />
            ) : (
              <ResultList
                entries={displayEntries}
                onSelect={(id) => { handleSelectEntry(id); setDrawerOpen(true); }}
                selectedId={selectedEntryId}
                locationFilter={locationFilter}
                onClearFilter={() => setLocationFilter(null)}
                language={language}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/locations/:id" element={<LocationPage />} />
          <Route path="/entries/:id" element={<EntryPage />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
