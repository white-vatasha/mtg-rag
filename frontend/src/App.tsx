import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Decks from "./pages/Decks";
import Home from "./pages/Home";
import Login from "./pages/Login";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="decks" element={<Decks />} />
        <Route path="login" element={<Login />} />
      </Route>
    </Routes>
  );
}
