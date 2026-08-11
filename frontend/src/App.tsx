/**
 * Routing, and the one decision above it: signed in or not.
 *
 * Everything inside `Shell` assumes a session. Rather than each screen
 * defending itself, the gate is here.
 */

import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { Shell } from "./components/Shell";
import { useSession } from "./lib/hooks";
import { Dashboard } from "./routes/Dashboard";
import { SignIn } from "./routes/SignIn";
import { Search } from "./routes/Search";
import { MapView } from "./routes/MapView";
import { Storage } from "./routes/Storage";
import {
  ArtifactDetail,
  Artifacts,
  ProjectDetail,
  Projects,
  SiteDetail,
  Sites,
} from "./routes/Archaeology";
import {
  Catalogue,
  CollectionDetail,
  Collections,
  NewObject,
  ObjectDetail,
} from "./routes/Museum";
import { CatalogueGrid } from "./routes/Grid";
import {
  NewArtifact,
  NewCollection,
  NewContext,
  NewProject,
  NewSite,
} from "./routes/NewRecords";
import {
  EquipmentDetailScreen,
  EquipmentList,
  KitScreen,
  KitTemplateScreen,
  KitTemplates,
  Kits,
  NewEquipment,
  NewStockLine,
  OutOnLoan,
  StockDetail,
  StockList,
} from "./routes/Inventory";
import {
  BudgetScreen,
  Budgets,
  Calendar,
  Expenses,
  MyTasks,
  Tasks,
} from "./routes/Management";
import { AdminUsers } from "./routes/Admin";
import { Appearance, MyProfile } from "./routes/Appearance";
import { Outreach, PostScreen } from "./routes/Social";
import {
  Activities,
  ActivityHub,
  ActivityScreen,
  NewActivity,
} from "./routes/Activities";
import { BatchEntry } from "./routes/Batch";
import { Gallery } from "./routes/Gallery";
import { Channels as MediaChannels } from "./routes/Channels";
import { Media } from "./routes/Media";
import { Requests } from "./routes/Requests";
import { SendFiles } from "./routes/Send";
import { ImportBatch, ImportUpload } from "./routes/Import";
import { Library } from "./routes/Library";
import { FloorPlanScreen, FloorPlansForLocation } from "./routes/FloorPlan";
import { Empty, Loading } from "./components/ui";

function NotFound() {
  return (
    <Empty title="That page does not exist">
      The link may be old, or the record may have been deleted.
    </Empty>
  );
}

export function App() {
  const { user, loading } = useSession();
  const location = useLocation();

  // The one page that has to work for somebody with no account: an invitation
  // to send files for one record. Checked before the session is even waited
  // for — a photographer following a link from their mailbox should not be
  // shown a sign-in form, and the page needs nothing a session would provide.
  if (location.pathname.startsWith("/send/")) {
    return (
      <Routes>
        <Route path="send/:token" element={<SendFiles />} />
      </Routes>
    );
  }

  if (loading) {
    return (
      <div className="boot">
        <Loading rows={3} label="Starting" />
      </div>
    );
  }

  if (!user) return <SignIn />;

  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Dashboard />} />
        <Route path="search" element={<Search />} />
        <Route path="map" element={<MapView />} />
        <Route path="photographs" element={<Gallery />} />
        <Route path="media" element={<Media />} />

        <Route path="projects" element={<Projects />} />
        {/* Before the :projectId route, or "new" is read as an id. */}
        <Route path="projects/new" element={<NewProject />} />
        <Route path="projects/:projectId" element={<ProjectDetail />} />
        <Route path="sites" element={<Sites />} />
        <Route path="sites/new" element={<NewSite />} />
        <Route path="sites/:siteId" element={<SiteDetail />} />
        <Route path="contexts/new" element={<NewContext />} />
        <Route path="artifacts" element={<Artifacts />} />
        <Route path="artifacts/new" element={<NewArtifact />} />
        <Route path="artifacts/:artifactId" element={<ArtifactDetail />} />

        <Route path="museum" element={<Catalogue />} />
        <Route path="museum/grid" element={<CatalogueGrid />} />
        {/* Before the :objectId route, or "new" is read as an id. */}
        <Route path="museum/objects/new" element={<NewObject />} />
        <Route path="museum/objects/:objectId" element={<ObjectDetail />} />
        {/* One import screen for every kind of record. The old museum-only
            paths still work: a bookmark from before should not 404. */}
        <Route path="import" element={<ImportUpload />} />
        <Route path="tray" element={<BatchEntry />} />
        <Route path="import/:batchId" element={<ImportBatch />} />
        <Route
          path="museum/import"
          element={<Navigate to="/import?type=museum_object" replace />}
        />
        <Route path="museum/import/:batchId" element={<ImportBatch />} />
        <Route path="museum/collections" element={<Collections />} />
        {/* Before the :collectionId route, or "new" is read as an id. */}
        <Route path="museum/collections/new" element={<NewCollection />} />
        <Route path="museum/collections/:collectionId" element={<CollectionDetail />} />

        <Route path="inventory/equipment" element={<EquipmentList />} />
        {/* Before the :equipmentId route, or "new" is read as an id. */}
        <Route path="inventory/equipment/new" element={<NewEquipment />} />
        <Route path="inventory/equipment/:equipmentId" element={<EquipmentDetailScreen />} />
        <Route path="inventory/out" element={<OutOnLoan />} />
        <Route path="inventory/stock" element={<StockList />} />
        <Route path="inventory/stock/new" element={<NewStockLine />} />
        <Route path="inventory/stock/:consumableId" element={<StockDetail />} />
        <Route path="inventory/kit-templates" element={<KitTemplates />} />
        <Route path="inventory/kit-templates/:templateId" element={<KitTemplateScreen />} />
        <Route path="inventory/kits" element={<Kits />} />
        <Route path="inventory/kits/:kitId" element={<KitScreen />} />

        <Route path="management/budgets" element={<Budgets />} />
        <Route path="management/budgets/:budgetId" element={<BudgetScreen />} />
        <Route path="management/expenses" element={<Expenses />} />
        <Route path="my-work" element={<MyTasks />} />
        <Route path="data-requests" element={<Requests />} />
        <Route path="management/tasks" element={<Tasks />} />
        <Route path="management/calendar" element={<Calendar />} />

        <Route path="activities" element={<ActivityHub />} />
        {/* Before the :activityId route, or these are read as identifiers. */}
        <Route path="activities/all" element={<Activities />} />
        <Route path="activities/new" element={<NewActivity />} />
        <Route path="activities/:activityId" element={<ActivityScreen />} />

        <Route path="social" element={<Outreach />} />
        <Route path="social/accounts" element={<MediaChannels />} />
        <Route path="social/posts/:postId" element={<PostScreen />} />

        <Route path="library" element={<Library />} />

        <Route path="storage" element={<Storage />} />
        <Route path="floorplans" element={<FloorPlansForLocation />} />
        <Route path="floorplans/:planId" element={<FloorPlanScreen />} />

        <Route path="admin/users" element={<AdminUsers />} />
        <Route path="admin/appearance" element={<Appearance />} />
        <Route path="profile" element={<MyProfile />} />

        <Route path="404" element={<NotFound />} />
        <Route path="*" element={<Navigate to="/404" replace />} />
      </Route>
    </Routes>
  );
}
