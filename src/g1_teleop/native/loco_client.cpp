// Author: Codex (IIC)
#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <cstdint>
#include <exception>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

#include <unitree/robot/b2/robot_state/robot_state_client.hpp>
#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/g1/loco/g1_loco_client.hpp>

namespace {

using unitree::robot::b2::RobotStateClient;
using unitree::robot::b2::ServiceState;
using unitree::robot::g1::LocoClient;

struct Clients {
    LocoClient loco;

    // Only the operator's one-shot status request needs the robot_state service.
    RobotStateClient& robot_state() {
        std::call_once(state_init, [&] {
            auto state = std::make_unique<RobotStateClient>();
            state->SetTimeout(1.f);
            state->Init();
            robot = std::move(state);
        });
        return *robot;
    }

private:
    std::once_flag state_init;
    std::unique_ptr<RobotStateClient> robot;
};

struct ClientObject {
    PyObject_HEAD
    Clients* sdk;
};

PyTypeObject client_type = {PyVarObject_HEAD_INIT(nullptr, 0)};

// Restore the interpreter lock before translating either the result or an exception.
class AllowThreads {
public:
    AllowThreads() : thread_(PyEval_SaveThread()) {}
    ~AllowThreads() { PyEval_RestoreThread(thread_); }

private:
    PyThreadState* thread_;
};

template <class Operation, class Convert>
PyObject* sdk_call(Operation operation, Convert convert) {
    try {
        auto result = [&] {
            AllowThreads unlocked;
            return operation();
        }();
        return convert(std::move(result));
    } catch (const std::exception& error) {
        PyErr_SetString(PyExc_RuntimeError, error.what());
    } catch (...) {
        PyErr_SetString(PyExc_RuntimeError, "Unitree SDK2 raised an unknown exception");
    }
    return nullptr;
}

Clients& client(PyObject* self) {
    return *reinterpret_cast<ClientObject*>(self)->sdk;
}

void destroy_client(PyObject* self) {
    delete reinterpret_cast<ClientObject*>(self)->sdk;
    Py_TYPE(self)->tp_free(self);
}

PyObject* connect_client(PyObject*, PyObject* args) {
    int domain;
    const char* interface;
    if (!PyArg_ParseTuple(args, "is:connect", &domain, &interface)) {
        return nullptr;
    }
    return sdk_call([&] {
        unitree::robot::ChannelFactory::Instance()->Init(domain, interface);
        auto sdk = std::make_unique<Clients>();
        sdk->loco.SetTimeout(0.5f);
        sdk->loco.Init();
        return sdk;
    }, [](std::unique_ptr<Clients> sdk) -> PyObject* {
        auto* result = PyObject_New(ClientObject, &client_type);
        if (result != nullptr) {
            result->sdk = sdk.release();
        }
        return reinterpret_cast<PyObject*>(result);
    });
}

template <int32_t (LocoClient::*Method)(int&)>
PyObject* get_fsm(PyObject* self, PyObject*) {
    int id = 0;
    return sdk_call([&] { return (client(self).loco.*Method)(id); }, [&](int status) {
        if (status != 0) {
            return Py_BuildValue("(iO)", status, Py_None);
        }
        return Py_BuildValue("(ii)", status, id);
    });
}

template <int32_t (LocoClient::*Method)(int)>
PyObject* set_mode(PyObject* self, PyObject* args) {
    int mode;
    if (!PyArg_ParseTuple(args, "i", &mode)) {
        return nullptr;
    }
    return sdk_call([&] { return (client(self).loco.*Method)(mode); }, PyLong_FromLong);
}

PyObject* move(PyObject* self, PyObject* args) {
    float vx, vy, yaw;
    if (!PyArg_ParseTuple(args, "fff:Move", &vx, &vy, &yaw)) {
        return nullptr;
    }
    return sdk_call([&] { return client(self).loco.Move(vx, vy, yaw); }, PyLong_FromLong);
}

PyObject* set_velocity(PyObject* self, PyObject* args) {
    float vx, vy, yaw, duration;
    if (!PyArg_ParseTuple(args, "ffff:SetVelocity", &vx, &vy, &yaw, &duration)) {
        return nullptr;
    }
    return sdk_call([&] { return client(self).loco.SetVelocity(vx, vy, yaw, duration); }, PyLong_FromLong);
}

PyObject* stop_move(PyObject* self, PyObject*) {
    return sdk_call([&] { return client(self).loco.StopMove(); }, PyLong_FromLong);
}

PyObject* get_server_api_version(PyObject* self, PyObject*) {
    return sdk_call([&] { return client(self).loco.GetServerApiVersion(); }, [](const std::string& version) {
        return PyUnicode_FromStringAndSize(version.data(), version.size());
    });
}

PyObject* service_list(PyObject* self, PyObject*) {
    std::vector<ServiceState> services;
    return sdk_call([&] { return client(self).robot_state().ServiceList(services); }, [&](int status) -> PyObject* {
        if (status != 0) {
            return Py_BuildValue("(iO)", status, Py_None);
        }
        PyObject* entries = PyList_New(services.size());
        if (entries == nullptr) {
            return nullptr;
        }
        for (size_t index = 0; index < services.size(); ++index) {
            const ServiceState& service = services[index];
            PyObject* entry = Py_BuildValue("(si)", service.name.c_str(), service.status);
            if (entry == nullptr) {
                Py_DECREF(entries);
                return nullptr;
            }
            PyList_SET_ITEM(entries, index, entry);
        }
        return Py_BuildValue("(iN)", status, entries);
    });
}

PyObject* get_pkg_version(PyObject* self, PyObject*) {
    std::string package;
    std::map<std::string, std::string> modules;
    return sdk_call([&] { return client(self).robot_state().GetPkgVersion(package, modules); }, [&](int status) -> PyObject* {
        if (status != 0) {
            return Py_BuildValue("(iOO)", status, Py_None, Py_None);
        }
        PyObject* versions = PyDict_New();
        if (versions == nullptr) {
            return nullptr;
        }
        for (const auto& [name, version] : modules) {
            PyObject* value = PyUnicode_FromStringAndSize(version.data(), version.size());
            if (value == nullptr || PyDict_SetItemString(versions, name.c_str(), value) < 0) {
                Py_XDECREF(value);
                Py_DECREF(versions);
                return nullptr;
            }
            Py_DECREF(value);
        }
        return Py_BuildValue("(isN)", status, package.c_str(), versions);
    });
}

PyMethodDef client_methods[] = {
    {"GetServerApiVersion", get_server_api_version, METH_NOARGS, nullptr},
    {"ServiceList", service_list, METH_NOARGS, nullptr},
    {"GetPkgVersion", get_pkg_version, METH_NOARGS, nullptr},
    {"GetFsmMode", get_fsm<&LocoClient::GetFsmMode>, METH_NOARGS, nullptr},
    {"GetFsmId", get_fsm<&LocoClient::GetFsmId>, METH_NOARGS, nullptr},
    {"SetFsmId", set_mode<&LocoClient::SetFsmId>, METH_VARARGS, nullptr},
    {"SetBalanceMode", set_mode<&LocoClient::SetBalanceMode>, METH_VARARGS, nullptr},
    {"SetSpeedMode", set_mode<&LocoClient::SetSpeedMode>, METH_VARARGS, nullptr},
    {"Move", move, METH_VARARGS, nullptr},
    {"SetVelocity", set_velocity, METH_VARARGS, nullptr},
    {"StopMove", stop_move, METH_NOARGS, nullptr},
    {nullptr, nullptr, 0, nullptr}
};

PyMethodDef module_methods[] = {
    {"connect", connect_client, METH_VARARGS, "Initialize the official G1 LocoClient on (domain, interface)."},
    {nullptr, nullptr, 0, nullptr}
};

PyModuleDef module = {PyModuleDef_HEAD_INIT, "_g1_loco", nullptr, -1, module_methods};

}  // namespace

PyMODINIT_FUNC PyInit__g1_loco() {
    client_type.tp_name = "_g1_loco.LocoClient";
    client_type.tp_basicsize = sizeof(ClientObject);
    client_type.tp_dealloc = destroy_client;
    client_type.tp_flags = Py_TPFLAGS_DEFAULT;
    client_type.tp_methods = client_methods;
    if (PyType_Ready(&client_type) < 0) {
        return nullptr;
    }
    return PyModule_Create(&module);
}
