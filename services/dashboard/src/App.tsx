// services/dashboard/src/app.tsx
import { Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { MLOps } from "./views/MLOps";
import { Search } from "./views/Search";
import { Triage } from "./views/Triage";

export default function App() {
    return (
        <Routes>
            <Route element={<Layout />}>
                <Route index element={<Triage />} />
                <Route path="/search" element={<Search />} />
                <Route path="/mlops" element={<MLOps />} />
            </Route>
        </Routes>
    );
}
