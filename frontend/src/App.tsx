/**
 * Routing, and the one decision above it: signed in or not.
 *
 * Everything inside `Shell` assumes a session. Rather than each screen
 * defending itself, the gate is here.
 */

import { Navigate, Route, Routes } from "react-router-dom";

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
import { Channels, Outreach, PostScreen } from "./routes/Social";
import {
  Activities,
  ActivityHub,
  ActivityScreen,
  NewActivity,
} from "./routes/Activities";
import { ImportBatch, ImportUpload } from "./routes/Import";
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
        <Route path="museum/import" element={<ImportUpload />} />
        <Route path="museum/import/:batchId" element={<ImportBatch />} />
        <Route path="museum/collections" element={<Collections />} />
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
        <Route path="management/tasks" element={<Tasks />} />
        <Route path="management/calendar" element={<Calendar />} />

        <Route path="activities" element={<ActivityHub />} />
        {/* Before the :activityId route, or these are read as identifiers. */}
        <Route path="activities/all" element={<Activities />} />
        <Route path="activities/new" element={<NewActivity />} />
        <Route path="activities/:activityId" element={<ActivityScreen />} />

        <Route path="social" element={<Outreach />} />
        <Route path="social/accounts" element={<Channels />} />
        <Route path="social/posts/:postId" element={<PostScreen />} />

        <Route path="storage" element={<Storage />} />
        <Route path="floorplans" element={<FloorPlansForLocation />} />
        <Route path="floorplans/:planId" element={<FloorPlanScreen />} />

        <Route path="admin/users" element={<AdminUsers />} />

        <Route path="404" element={<NotFound />} />
        <Route path="*" element={<Navigate to="/404" replace />} />
      </Route>
    </Routes>
  );
}
